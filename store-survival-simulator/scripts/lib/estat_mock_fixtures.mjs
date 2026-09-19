/**
 * generate_area_data.test.mjs 専用のオフラインfixture。
 *
 * このサンドボックス（および多くのCI環境）では unpkg.com / api.e-stat.go.jp への
 * 実アクセスがネットワークポリシーでブロックされうる（README/design-doc記載の
 * 既知の制約と同じ）。実際のe-Statキーが無くても scripts/generate_area_data.mjs の
 * ブラウザ操作ロジック（ダイアログ処理・ダウンロード捕捉・index.json更新・
 * ゼロセットアップ起動確認）を検証できるよう、Leaflet/Turf本体と
 * e-Stat API応答を Playwright の page.route でスタブする。
 *
 * 統計データの中身はテスト用のダミー値であり、実際の人口動態を表さない。
 * ここを実データ取得ロジックの仕様として扱わないこと（本体は index.html 側）。
 */
import fs from "node:fs/promises";
import path from "node:path";

// index.htmlが読み込むCDNパッケージと同一バージョン。ズレるとAPI差分で壊れるため、
// package.json の devDependencies と揃えて管理する。
export const LEAFLET_VERSION = "1.9.4";
export const TURF_MAJOR = "6";

function tableInf({ id, title, tableName, surveyDate }) {
  return {
    "@id": id,
    TITLE: { "$": title },
    TITLE_SPEC: { TABLE_NAME: tableName },
    SURVEY_DATE: surveyDate
  };
}

function statsListResponse(tableInfList) {
  return {
    GET_STATS_LIST: {
      RESULT: { STATUS: 0 },
      DATALIST_INF: {
        NUMBER: tableInfList.length,
        TABLE_INF: tableInfList.length === 1 ? tableInfList[0] : tableInfList
      }
    }
  };
}

function popStatsDataResponse(meshCodes, seedOffset) {
  const classInf = {
    CLASS_INF: {
      CLASS_OBJ: [
        {
          "@id": "cat01",
          CLASS: [
            { "@code": "0010", "@level": "1", "@name": "総数" },
            { "@code": "0020", "@level": "1", "@name": "０～１４歳" },
            { "@code": "0030", "@level": "1", "@name": "１５～６４歳" },
            { "@code": "0040", "@level": "1", "@name": "６５歳以上" }
          ]
        }
      ]
    }
  };
  const values = [];
  meshCodes.forEach((code, i) => {
    // 決定論的なダミー人口(テスト用)。実データの分布を模してはいない。
    const base = 800 + ((seedOffset + i * 37) % 400);
    const young = Math.round(base * 0.12);
    const active = Math.round(base * 0.6);
    const senior = base - young - active;
    const rows = [
      ["0010", base],
      ["0020", young],
      ["0030", active],
      ["0040", senior]
    ];
    rows.forEach(([cat01, val]) => {
      values.push({ "@cat01": cat01, "@cat02": "1", "@area": code, "$": String(val) });
    });
  });
  return {
    GET_STATS_DATA: {
      RESULT: { STATUS: 0 },
      STATISTICAL_DATA: {
        CLASS_INF: classInf.CLASS_INF,
        DATA_INF: { VALUE: values }
      }
    }
  };
}

function econStatsDataResponse(meshCodes, seedOffset) {
  const values = [];
  meshCodes.forEach((code, i) => {
    const base = 3 + ((seedOffset + i * 5) % 6);
    [
      ["0100", base],
      ["0110", Math.max(0, base - 2)],
      ["0140", Math.max(0, base - 1)],
      ["0150", Math.max(0, base - 3)]
    ].forEach(([cat01, val]) => {
      values.push({ "@cat01": cat01, "@area": code, "$": String(val) });
    });
  });
  return {
    GET_STATS_DATA: {
      RESULT: { STATUS: 0 },
      STATISTICAL_DATA: { DATA_INF: { VALUE: values } }
    }
  };
}

/**
 * page に対し、Leaflet/Turf CDNとe-Stat APIをローカルfixtureへ差し替えるrouteを登録する。
 * pkgCache には { leafletJs, leafletCss, turfJs } のローカルファイルパスを渡す。
 */
export async function installMockRoutes(page, { pkgCache }) {
  const [leafletJs, leafletCss, turfJs] = await Promise.all([
    fs.readFile(pkgCache.leafletJs, "utf-8"),
    fs.readFile(pkgCache.leafletCss, "utf-8"),
    fs.readFile(pkgCache.turfJs, "utf-8")
  ]);

  await page.route(`https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.js`, (route) =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: leafletJs })
  );
  await page.route(`https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.css`, (route) =>
    route.fulfill({ status: 200, contentType: "text/css", body: leafletCss })
  );
  await page.route(`https://unpkg.com/@turf/turf@${TURF_MAJOR}/turf.min.js`, (route) =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: turfJs })
  );
  // 地図タイルは実データ検証に不要。空画像で即応答し、余計な待ちを作らない。
  await page.route("https://*.tile.openstreetmap.org/**", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: Buffer.from([]) })
  );

  await page.route("https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList**", (route) => {
    const url = new URL(route.request().url());
    const searchWord = url.searchParams.get("searchWord") || "";
    const isEcon = url.searchParams.get("statsCode") === "00200553";
    if (isEcon) {
      const region = (searchWord.match(/M(\d{4})/) || [])[1] || "0000";
      const body = statsListResponse([
        tableInf({
          id: `MOCK-ECON-${region}`,
          title: `経済センサス-活動調査 M${region} 産業（大分類）別事業所数`,
          tableName: "産業（大分類）別事業所数及び従業者数",
          surveyDate: "201606"
        })
      ]);
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      return;
    }
    const year = searchWord.includes("令和2年") ? "令和2年" : "平成27年";
    const region = (searchWord.match(/M(\d{4})/) || [])[1] || "0000";
    const body = statsListResponse([
      tableInf({
        id: `MOCK-POP-${year}-${region}`,
        title: `${year}国勢調査 M${region} 人口及び世帯`,
        tableName: year === "令和2年" ? "人口及び世帯" : "人口等基本集計",
        surveyDate: year === "令和2年" ? "202010" : "201510"
      })
    ]);
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.route("https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData**", (route) => {
    const url = new URL(route.request().url());
    const statsDataId = url.searchParams.get("statsDataId") || "";
    const cdArea = (url.searchParams.get("cdArea") || "").split(",").filter(Boolean);
    const seed = Array.from(statsDataId).reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    const body = statsDataId.startsWith("MOCK-ECON-")
      ? econStatsDataResponse(cdArea, seed)
      : popStatsDataResponse(cdArea, seed);
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

/**
 * npm でインストールした devDependencies（leaflet / @turf/turf）から、
 * index.htmlが読むCDN版と同一バージョンのファイルを指す。
 */
export function resolvePkgCache(nodeModulesDir) {
  return {
    leafletJs: path.join(nodeModulesDir, "leaflet/dist/leaflet.js"),
    leafletCss: path.join(nodeModulesDir, "leaflet/dist/leaflet.css"),
    turfJs: path.join(nodeModulesDir, "@turf/turf/turf.min.js")
  };
}
