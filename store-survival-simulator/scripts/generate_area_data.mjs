#!/usr/bin/env node
/**
 * SS-01-S01-3: サンプルエリアデータを自動生成し、data/areas/ へ反映するスクリプト。
 *
 * Notion Blocker（e-StatアプリケーションIDのSecret設定）が解消された後、
 * .github/workflows/store-survival-generate-area-data.yml から実行される想定。
 * index.html の「別の場所を診断する」フローをPlaywrightで自動操作し、
 * downloadAreaPack() が生成するJSONをそのまま data/areas/ に保存する。
 *
 * ライブ取得と事前生成データは index.html 内の同じ buildMeshGeoJson() を通る設計
 * （README「動作の仕組み」参照）なので、ここで統計データの変換ロジックを
 * 重複実装しない。このスクリプトは「ブラウザ操作の自動化」だけを担う。
 *
 * 使い方（事前に対象ディレクトリをHTTPで配信しておくこと。README「動かし方」参照）:
 *   ESTAT_APP_ID=xxxx node scripts/generate_area_data.mjs \
 *     --location "35.681236,139.767125" \
 *     --name "東京駅周辺（サンプル）" \
 *     [--business conveni] \
 *     [--base-url http://127.0.0.1:8080/] \
 *     [--out-dir data/areas] \
 *     [--verify-zero-setup]
 */
import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, ".."); // store-survival-simulator/

// index.html の downloadAreaPack() と同一のスラッグ化ロジック。ズレるとファイル名が
// 一致しなくなるため、あちらを変更したら必ずこちらも合わせる。
function slugifyAreaName(name) {
  return (name || "area").trim().replace(/\s+/g, "-").replace(/[^\w\-一-龠ぁ-んァ-ヶ]/g, "") || "area";
}

export function parseArgs(argv) {
  const args = {
    baseUrl: "http://127.0.0.1:8080/",
    outDir: path.join(REPO_ROOT, "data/areas"),
    business: "conveni",
    timeoutMs: 180000,
    verifyZeroSetup: false
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    if (a === "--location") args.location = next();
    else if (a === "--name") args.name = next();
    else if (a === "--business") args.business = next();
    else if (a === "--base-url") args.baseUrl = next();
    else if (a === "--out-dir") args.outDir = path.resolve(next());
    else if (a === "--timeout-ms") args.timeoutMs = Number(next());
    else if (a === "--verify-zero-setup") args.verifyZeroSetup = true;
    else throw new Error(`unknown argument: ${a}`);
  }
  return args;
}

/**
 * 「別の場所を診断する」フローを自動操作し、エリアデータを1件生成してdata/areas/へ保存する。
 * page は呼び出し側で baseUrl へ goto 済みであること。
 */
export async function generateAreaData({
  page,
  appId,
  location,
  name,
  business = "conveni",
  outDir,
  timeoutMs = 180000,
  log = console.log
}) {
  if (!appId) throw new Error("ESTAT_APP_ID is required (env var), but was empty.");
  if (!location) throw new Error("--location (lat,lng) is required.");
  if (!name) throw new Error("--name (area display name) is required.");
  if (!outDir) throw new Error("outDir is required.");

  // <details>のクリックトグルは開閉が不確実(既に開いている場合に閉じてしまう等)なため、
  // 明示的にopen=trueへ設定する。
  await page.evaluate(() => {
    document.getElementById("liveModeDetails").open = true;
  });
  await page.fill("#storeLocationInput", location);
  await page.fill("#appIdInput", appId);
  await page.check("#exportAreaCheckbox");

  const bizCard = page.locator(`.biz-card[data-id="${business}"]`);
  if ((await bizCard.count()) === 0) {
    throw new Error(`business id "${business}" not found among .biz-card options.`);
  }
  await bizCard.click();

  // startGame() は取得完了後に window.prompt(エリア名) を呼ぶ。name で自動応答する。
  page.once("dialog", async (dialog) => {
    log(`[dialog] ${dialog.type()}: ${dialog.message()}`);
    await dialog.accept(name);
  });

  const downloadPromise = page.waitForEvent("download", { timeout: timeoutMs });
  await page.click("#startGameBtn");

  let download;
  try {
    download = await downloadPromise;
  } catch (e) {
    const statusTexts = await page.evaluate(() => {
      const ids = ["setupStatus", "storeLocationStatus", "areaStatus", "setupBizStatus"];
      const out = {};
      ids.forEach((id) => {
        const el = document.getElementById(id);
        out[id] = el ? el.textContent : null;
      });
      return out;
    });
    throw new Error(
      `Timed out waiting for the area file download after clicking start. ` +
        `Page status texts: ${JSON.stringify(statusTexts)}. Original error: ${e.message}`
    );
  }

  await fs.mkdir(outDir, { recursive: true });

  // Chromiumのblob URLダウンロードは、日本語を含むファイル名だと
  // suggestedFilename()が "download" 固定になることがある（実機確認済み）。
  // そのため一旦仮名で保存し、中身のname(=downloadAreaPack()に渡した名前)から
  // アプリ本体と同じアルゴリズムでスラッグを算出し直してリネームする。
  const tmpPath = path.join(outDir, `._download_tmp_${process.pid}_${Date.now()}.json`);
  await download.saveAs(tmpPath);

  const raw = await fs.readFile(tmpPath, "utf-8");
  const pack = JSON.parse(raw);
  if (pack.schema_version !== 1) {
    await fs.rm(tmpPath, { force: true });
    throw new Error(`Unexpected schema_version in generated file: ${pack.schema_version}`);
  }

  const suggested = `${slugifyAreaName(pack.name || name)}.json`;
  const destPath = path.join(outDir, suggested);
  await fs.rename(tmpPath, destPath);
  const meshCount = Array.isArray(pack.dataset && pack.dataset.meshCodes)
    ? pack.dataset.meshCodes.length
    : 0;
  if (meshCount === 0) {
    throw new Error("Generated area file has 0 mesh cells; refusing to register it in index.json.");
  }

  const indexPath = path.join(outDir, "index.json");
  let indexJson = { areas: [] };
  try {
    const parsed = JSON.parse(await fs.readFile(indexPath, "utf-8"));
    if (Array.isArray(parsed.areas)) indexJson = parsed;
  } catch (e) {
    // index.json が無い、または壊れている場合は新規作成として続行する。
  }
  indexJson.areas = indexJson.areas.filter((a) => a.file !== suggested);
  indexJson.areas.push({ name: pack.name, file: suggested, mesh_count: meshCount });
  await fs.writeFile(indexPath, JSON.stringify(indexJson, null, 2) + "\n", "utf-8");

  log(`[generate_area_data] wrote ${destPath} (mesh_count=${meshCount})`);
  log(`[generate_area_data] updated ${indexPath}`);

  return { file: suggested, name: pack.name, meshCount, destPath, indexPath };
}

/**
 * ゼロセットアップ起動フローの実機検証（Acceptance Criteria該当部分）。
 * エリア一覧から選ぶだけでゲーム画面へ到達できることを確認する。
 * e-Statキー・店舗座標入力には一切触れない。
 */
export async function verifyZeroSetupStart({ page, baseUrl, areaName, business = "conveni", log = console.log }) {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });

  await page.waitForFunction(
    (targetName) => {
      const sel = document.getElementById("areaSelect");
      if (!sel || sel.disabled) return false;
      return Array.from(sel.options).some((o) => o.textContent === targetName);
    },
    areaName,
    { timeout: 15000 }
  );
  await page.selectOption("#areaSelect", { label: areaName });

  const bizCard = page.locator(`.biz-card[data-id="${business}"]`);
  await bizCard.click();

  await page.click("#startGameBtn");
  await page.waitForFunction(
    () => {
      const gameRoot = document.getElementById("gameRoot");
      const setupScreen = document.getElementById("setupScreen");
      return !!gameRoot && !!setupScreen && gameRoot.style.display !== "none" && setupScreen.style.display === "none";
    },
    { timeout: 20000 }
  );

  log(`[verify_zero_setup] reached #gameRoot for area "${areaName}" without any API key input.`);
  return true;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const appId = process.env.ESTAT_APP_ID;

  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ acceptDownloads: true });
    const page = await context.newPage();
    page.on("console", (msg) => console.log(`[browser:${msg.type()}] ${msg.text()}`));
    page.on("pageerror", (err) => console.error(`[pageerror] ${err.message}`));

    await page.goto(args.baseUrl, { waitUntil: "domcontentloaded" });
    const result = await generateAreaData({
      page,
      appId,
      location: args.location,
      name: args.name,
      business: args.business,
      outDir: args.outDir,
      timeoutMs: args.timeoutMs
    });
    console.log("[generate_area_data] SUCCESS", JSON.stringify(result));

    if (args.verifyZeroSetup) {
      await verifyZeroSetupStart({ page, baseUrl: args.baseUrl, areaName: result.name, business: args.business });
      console.log("[generate_area_data] zero-setup E2E check passed.");
    }
  } catch (e) {
    console.error("[generate_area_data] FAILED:", e.message);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
