import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import requests
import shapefile

from _env import load_app_id

APP_ID = load_app_id()
WARD_CODE = "12103"  # 千葉市稲毛区
AREA_FROM = f"{WARD_CODE}000000"
AREA_TO = f"{WARD_CODE}999999"

TABLE_BASE = "8003006730"    # 男女別人口総数及び世帯総数 (令和2年)
TABLE_AGE = "8003006752"     # 年齢（５歳階級）別人口 (令和2年)
TABLE_FAMILY = "8003006873"  # 世帯の家族類型別一般世帯数 (令和2年)
TABLE_AGE_2015 = "8003000081"  # 年齢（５歳階級）別人口 (平成27年、実コーホート変化率算出用)
CENSUS_INTERVAL_YEARS = 5

DATA_DIR = Path(__file__).parent.parent / "data"
SHAPEFILE_DIR = DATA_DIR / "cache" / "r2ka12" / "r2ka12"


def fetch(stats_data_id):
    resp = requests.get(
        "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData",
        params={
            "appId": APP_ID,
            "statsDataId": stats_data_id,
            "searchKind": "2",
            "lang": "J",
            "cdAreaFrom": AREA_FROM,
            "cdAreaTo": AREA_TO,
        },
        timeout=60,
    )
    resp.raise_for_status()
    root = resp.json()["GET_STATS_DATA"]
    if root["RESULT"]["STATUS"] != 0:
        raise RuntimeError(f"{stats_data_id}: {root['RESULT']}")
    return root["STATISTICAL_DATA"]


def area_levels(stat_data):
    levels = {}
    names = {}
    for obj in stat_data["CLASS_INF"]["CLASS_OBJ"]:
        if obj["@id"] == "area":
            classes = obj["CLASS"]
            if isinstance(classes, dict):
                classes = [classes]
            for c in classes:
                levels[c["@code"]] = c.get("@level")
                names[c["@code"]] = c["@name"].strip("　 ")
    return levels, names


def numeric(v):
    raw = v["$"]
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None  # suppressed ('X' / '-' / etc.)


print("fetching base table (population & households)...")
base = fetch(TABLE_BASE)
levels, names = area_levels(base)
leaf_codes = {code for code, lv in levels.items() if lv in ("2", "4") and code.startswith(WARD_CODE)}
print(f"leaf-level town/chome areas in {WARD_CODE}: {len(leaf_codes)}")

stats = {code: {"key_code": code, "name": names[code]} for code in leaf_codes}

for v in base["DATA_INF"]["VALUE"]:
    area = v["@area"]
    if area not in leaf_codes:
        continue
    if v["@cat01"] == "0010":
        stats[area]["population"] = numeric(v)
    elif v["@cat01"] == "0040":
        stats[area]["households_total"] = numeric(v)

print("fetching age-group table...")
age = fetch(TABLE_AGE)
for v in age["DATA_INF"]["VALUE"]:
    area = v["@area"]
    if area not in leaf_codes:
        continue
    cat = v["@cat01"]
    val = numeric(v)
    if val is None:
        continue
    if cat in ("0050", "0060"):  # 15-19, 20-24
        stats[area]["young_pop"] = stats[area].get("young_pop", 0) + val
    elif cat in ("0140", "0150"):  # 60-64, 65-69
        stats[area]["senior_labor"] = stats[area].get("senior_labor", 0) + val
    # GDD v6: 3区分人口（現役25-59 / シニア60+）。若年(15-24)は young_pop をそのまま流用。
    if cat in ("0070", "0080", "0090", "0100", "0110", "0120", "0130"):  # 25-29 ... 55-59
        stats[area]["pop_active"] = stats[area].get("pop_active", 0) + val
    elif cat in ("0140", "0190"):  # 60-64 + 総数65歳以上(rollup) = 60歳以上
        stats[area]["pop_senior"] = stats[area].get("pop_senior", 0) + val

print("fetching household family-type table...")
family = fetch(TABLE_FAMILY)
for v in family["DATA_INF"]["VALUE"]:
    area = v["@area"]
    if area not in leaf_codes:
        continue
    cat = v["@cat01"]
    val = numeric(v)
    if val is None:
        continue
    if cat == "0050":  # 夫婦と子供から成る世帯 (family_hh proxy)
        stats[area]["family_hh"] = val
    elif cat == "0090":  # 65歳以上世帯員のいる一般世帯総数 (senior_hh proxy)
        stats[area]["senior_hh"] = val

for code in leaf_codes:
    s = stats[code]
    s["pop_young"] = s.get("young_pop", 0)
    s.setdefault("pop_active", 0)
    s.setdefault("pop_senior", 0)

print("fetching 2015 age-group table (for real cohort growth rates)...")
age2015 = fetch(TABLE_AGE_2015)
pop2015 = {code: {} for code in leaf_codes}
for v in age2015["DATA_INF"]["VALUE"]:
    area = v["@area"]
    if area not in leaf_codes:
        continue
    cat = v["@cat01"]
    val = numeric(v)
    if val is None:
        continue
    if cat in ("0050", "0060"):
        pop2015[area]["young"] = pop2015[area].get("young", 0) + val
    elif cat in ("0070", "0080", "0090", "0100", "0110", "0120", "0130"):
        pop2015[area]["active"] = pop2015[area].get("active", 0) + val
    elif cat in ("0140", "0190"):
        pop2015[area]["senior"] = pop2015[area].get("senior", 0) + val

# 町丁目ごとの年率 = (2020年値 / 2015年値)^(1/5) - 1。
# 単純な同一区分同士の比較（年齢シフトを追跡するコーホート法ではない簡易版）。
# 2015年に対応データがない・0の町丁目は、後段でこの区に実在する年率の
# 人口加重平均（フォールバック）で補う。
BRACKETS = [("young", "pop_young"), ("active", "pop_active"), ("senior", "pop_senior")]
rate_num = {b: 0.0 for b, _ in BRACKETS}   # 加重平均の分子 (rate * weight)
rate_den = {b: 0.0 for b, _ in BRACKETS}   # 加重平均の分母 (weight)

for code in leaf_codes:
    s = stats[code]
    p15 = pop2015.get(code, {})
    for bracket, key2020 in BRACKETS:
        v2020 = s.get(key2020, 0)
        v2015 = p15.get(bracket, 0)
        if v2015 and v2015 > 0 and v2020 and v2020 > 0:
            rate = (v2020 / v2015) ** (1 / CENSUS_INTERVAL_YEARS) - 1
            s[f"rate_{bracket}"] = rate
            rate_num[bracket] += rate * v2020
            rate_den[bracket] += v2020

fallback_rate = {
    bracket: (rate_num[bracket] / rate_den[bracket] if rate_den[bracket] > 0 else 0.0)
    for bracket, _ in BRACKETS
}
print("ward-wide weighted-average annual rates (fallback for unmatched towns):", fallback_rate)

unmatched = 0
for code in leaf_codes:
    s = stats[code]
    for bracket, _ in BRACKETS:
        key = f"rate_{bracket}"
        if key not in s:
            s[key] = fallback_rate[bracket]
            unmatched += 1
print(f"{unmatched} (town x bracket) values used the ward-wide fallback rate (no 2015 match)")

print("reading boundary shapefile...")
sf = shapefile.Reader(str(SHAPEFILE_DIR), encoding="shift_jis")
features = []
matched = 0
for sr in sf.shapeRecords():
    key_code = str(sr.record["KEY_CODE"])
    if key_code not in stats:
        continue
    matched += 1
    props = stats[key_code]
    features.append({
        "type": "Feature",
        "geometry": sr.shape.__geo_interface__,
        "properties": props,
    })

print(f"matched geometry for {matched}/{len(leaf_codes)} leaf areas")

missing = [c for c in leaf_codes if c not in {f["properties"]["key_code"] for f in features}]
if missing:
    print(f"WARNING: {len(missing)} leaf areas had stats but no matching polygon:", missing[:10])

geojson = {"type": "FeatureCollection", "name": "inage_ku_2020", "features": features}

out_path = DATA_DIR / "inage_ku.geojson"
out_path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
print("wrote", out_path, f"({out_path.stat().st_size:,} bytes)")

# quick sanity print
for f in features[:5]:
    print(f["properties"])
