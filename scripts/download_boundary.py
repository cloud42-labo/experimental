import io
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import requests

PREF_CODE = "12"  # 千葉県
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
ZIP_PATH = CACHE_DIR / f"r2ka{PREF_CODE}.zip"

if ZIP_PATH.exists():
    print(f"already downloaded: {ZIP_PATH} ({ZIP_PATH.stat().st_size:,} bytes)")
else:
    print("downloading boundary shapefile for prefecture", PREF_CODE, "...")
    resp = requests.get(
        "https://www.e-stat.go.jp/gis/statmap-search/data",
        params={
            "dlserveyId": "A002005212020",
            "code": PREF_CODE,
            "coordSys": "1",
            "format": "shape",
            "downloadType": "5",
            "datum": "2011",
        },
        timeout=180,
    )
    resp.raise_for_status()
    print("content-type:", resp.headers.get("content-type"), "size:", len(resp.content))
    ZIP_PATH.write_bytes(resp.content)

with zipfile.ZipFile(ZIP_PATH) as zf:
    names = zf.namelist()
    print("files in zip:")
    for n in names:
        print(" ", n)
    extract_dir = CACHE_DIR / f"r2ka{PREF_CODE}"
    zf.extractall(extract_dir)
    print("extracted to", extract_dir)
