#!/usr/bin/env node
/**
 * SS-01-S04-6-E2E: store-survival-simulatorのブラウザE2E（3パターン通し検証）。
 *
 * AC「①良好継続で10年目到達・終了、②悪化継続でcrisis遷移、③途中撤退でwithdraw遷移」を、
 * 実際のindex.html（ダミーではなく本体）をPlaywright/Chromiumで直接操作して検証する。
 * 進行バー(#turnProgress)・履歴(#turnHistoryList)・やり直し(#restartGameBtn)も
 * あわせて自動確認する。e-Stat/ライブ取得は一切使わず、同梱の
 * data/areas/東京駅周辺サンプル.json（パッケージ済みエリア）のゼロセットアップ起動
 * フローだけを使う（generate_area_data.test.mjsと同じくunpkg.com経由のLeaflet/Turfだけは
 * このサンドボックスのegressポリシーでブロックされるため、lib/estat_mock_fixtures.mjsで
 * npm版に差し替える。e-Stat API自体は一切呼ばない）。
 *
 * スクリーンショット差分は取得しない（AC「必要なら」は任意）。3パターンとも
 * gameOverScreen/turnHistoryList/turnProgressの実際のDOM内容で状態を検証しており、
 * 画像比較を追加しなくても回帰は検出できるため。
 *
 * 使い方: node scripts/e2e_three_period_loop.test.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs/promises";
import fssync from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

import { verifyZeroSetupStart } from "./generate_area_data.mjs";
import { installMockRoutes, resolvePkgCache } from "./lib/estat_mock_fixtures.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, ".."); // store-survival-simulator/

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript",
  ".mjs": "application/javascript",
  ".json": "application/json",
  ".css": "text/css",
  ".png": "image/png",
  ".md": "text/plain; charset=utf-8"
};

// generate_area_data.test.mjsと同じ静的配信パターン（file://だとモジュール/CORSで壊れるため
// ローカルHTTPで配信する）。
function startStaticServer(rootDir, port) {
  const server = http.createServer(async (req, res) => {
    try {
      const urlPath = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
      let filePath = path.join(rootDir, urlPath === "/" ? "index.html" : urlPath);
      if (!filePath.startsWith(rootDir)) {
        res.writeHead(403);
        res.end();
        return;
      }
      const stat = await fs.stat(filePath).catch(() => null);
      if (!stat || stat.isDirectory()) {
        res.writeHead(404);
        res.end("not found");
        return;
      }
      const body = await fs.readFile(filePath);
      const ext = path.extname(filePath);
      res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" });
      res.end(body);
    } catch (e) {
      res.writeHead(500);
      res.end(String(e));
    }
  });
  return new Promise((resolve, reject) => {
    server.listen(port, "127.0.0.1", () => resolve(server));
    server.on("error", reject);
  });
}

// data/areas/index.json に登録済みのパッケージ済みエリア名（実行時に読み直し、
// ファイル名をテストコードにハードコードしない）。
async function packagedAreaName() {
  const indexPath = path.join(REPO_ROOT, "data", "areas", "index.json");
  const parsed = JSON.parse(await fs.readFile(indexPath, "utf-8"));
  assert.ok(Array.isArray(parsed.areas) && parsed.areas.length > 0, "data/areas/index.json に同梱エリアが1件も登録されていません");
  return parsed.areas[0].name;
}

/** #setupBizGridに実際に描画されている業種カードの中から、最初の1件のdata-idを取る。 */
async function firstBusinessId(page) {
  await page.waitForSelector("#setupBizGrid .biz-card", { timeout: 10000 });
  const id = await page.locator("#setupBizGrid .biz-card").first().getAttribute("data-id");
  assert.ok(id, "#setupBizGridに業種カードが1枚も無い");
  return id;
}

/** ④の経営判断カードから1枚選ぶ（#mgmtDecisionGrid内、業種カードとdata-idの名前空間は独立）。 */
async function selectDecision(page, decisionId) {
  const card = page.locator(`#mgmtDecisionGrid .biz-card[data-id="${decisionId}"]`);
  assert.equal(await card.count(), 1, `経営判断カード data-id="${decisionId}" が見つからない`);
  await card.click();
}

async function turnHistoryCount(page) {
  return page.locator("#turnHistoryList .turn-history-item").count();
}

async function currentTurnLabel(page) {
  return page.locator("#turnProgress .turn-step.current").textContent();
}

async function doneTurnStepCount(page) {
  return page.locator("#turnProgress .turn-step.done").count();
}

async function gameOverInfo(page) {
  return page.evaluate(() => {
    const el = document.getElementById("gameOverScreen");
    if (!el || el.style.display === "none") return { visible: false };
    const text = el.textContent || "";
    let reason = "unknown";
    if (text.includes("撤退という経営判断を下しました")) reason = "withdraw";
    else if (text.includes("連続で経営が深刻な状態から回復しませんでした")) reason = "crisis";
    return { visible: true, reason, text };
  });
}

/** advanceTurnBtnをクリックし、turnHistoryListへの追記（=クリックが実際に処理された）を待つ。 */
async function clickAdvanceAndWait(page) {
  const before = await turnHistoryCount(page);
  await page.click("#advanceTurnBtn");
  await page.waitForFunction(
    (prev) => document.querySelectorAll("#turnHistoryList .turn-history-item").length > prev,
    before,
    { timeout: 10000 }
  );
}

/**
 * パターン①: 良好継続 → 10年目に到達して終了する。
 * 「A. 保全・現状維持」を毎期選び続ける。客層・労働力の適性がすでに良好（同梱エリアは
 * 人口が10年間増加し続ける前提のサンプルのため、全業種で「良好」判定になる）なので、
 * 現状維持を選び続ける限りdisqualify(worst===0)には触れず、危機的状態には陥らない。
 */
async function runPatternGoodEnding(page, baseUrl, areaName, log) {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  const business = await firstBusinessId(page);
  await verifyZeroSetupStart({ page, baseUrl, areaName, business, log });

  assert.equal(await currentTurnLabel(page), "現在", "ゲーム開始直後は進行バーの「現在」がcurrentであるべき");
  assert.equal(await turnHistoryCount(page), 0, "開始直後は履歴が空であるべき");

  const seenLabels = [await currentTurnLabel(page)];
  let clicks = 0;
  for (let i = 0; i < 5; i++) {
    await selectDecision(page, "maintain");

    const isLast = await page.evaluate(() => document.getElementById("advanceTurnBtn").disabled);
    if (isLast) break;

    const doneBefore = await doneTurnStepCount(page);
    await clickAdvanceAndWait(page);
    clicks++;

    const go = await gameOverInfo(page);
    assert.equal(go.visible, false, `良好継続プレイのはずが${clicks}回目のクリックでgameOverになった: ${JSON.stringify(go)}`);

    const label = await currentTurnLabel(page);
    assert.notEqual(label, seenLabels[seenLabels.length - 1], "進行バーのcurrentラベルが期を進めても変わっていない");
    seenLabels.push(label);

    const doneAfter = await doneTurnStepCount(page);
    assert.ok(doneAfter > doneBefore, "期を進めたのに進行バーのdoneステップ数が増えていない");

    const histCount = await turnHistoryCount(page);
    assert.equal(histCount, clicks, `turnHistoryListの件数(${histCount})が進めた期の回数(${clicks})と一致しない`);
  }

  assert.equal(clicks, 3, "TURN_CHECKPOINTS=[0,3,6,10]のはずなので、10年目到達まで進める回数は3回のはず");
  assert.deepEqual(seenLabels, ["現在", "3年目", "6年目", "10年目"], "進行バーが現在→3年目→6年目→10年目の順に進んでいない");

  const btnText = await page.locator("#advanceTurnBtn").textContent();
  assert.equal(btnText, "10年目に到達しました", "10年目到達後のボタン文言が想定と違う");
  const btnDisabled = await page.evaluate(() => document.getElementById("advanceTurnBtn").disabled);
  assert.equal(btnDisabled, true, "10年目到達後はadvanceTurnBtnがdisabledであるべき");

  const go = await gameOverInfo(page);
  assert.equal(go.visible, false, "良好継続プレイは10年目到達で終了し、gameOverScreenは出ないはず");

  log(`[pattern1] business=${business} 10年目到達まで${clicks}回の期進行、gameOverなし: OK`);
  return { business };
}

/**
 * パターン②: 悪化継続 → crisis遷移。
 * 「D. 競合を叩く」を毎期選び続ける。fightのdisqualify条件は finTier!==2 || compTier===0 で、
 * financeプロファイル未入力時の中立値(finTier=1)からは絶対にfinTier===2に届かないため、
 * 毎期確実に「筋が悪い」判定になり、次期以降の持ち越し効果(carryoverEffect)を毎期悪化させ続ける。
 * withdraw(E)のendorse条件(worst===0 && finTier===0)をisCriticalの定義としてそのまま使い、
 * 「撤退する」カードのバッジが「妥当」になった時点をcriticalのオラクルとして読む。
 */
async function runPatternCrisis(page, baseUrl, areaName, log) {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  const business = await firstBusinessId(page);
  await verifyZeroSetupStart({ page, baseUrl, areaName, business, log });

  let clicks = 0;
  let go = { visible: false };
  const withdrawBadgeHistory = [];
  for (let i = 0; i < 5 && !go.visible; i++) {
    const badge = await page.locator('#mgmtDecisionGrid .biz-card[data-id="withdraw"] .mgmt-verdict-badge').textContent();
    withdrawBadgeHistory.push(badge);

    await selectDecision(page, "fight");
    const isLast = await page.evaluate(() => document.getElementById("advanceTurnBtn").disabled);
    if (isLast) break;

    await clickAdvanceAndWait(page);
    clicks++;
    go = await gameOverInfo(page);
  }

  assert.equal(go.visible, true, `悪化継続プレイのはずがgameOverにならなかった（撤退バッジ履歴: ${JSON.stringify(withdrawBadgeHistory)}）`);
  assert.equal(go.reason, "crisis", `gameOverの理由が想定と違う: ${JSON.stringify(go)}`);

  const histCount = await turnHistoryCount(page);
  assert.equal(histCount, clicks, `crisis遷移時のturnHistoryList件数(${histCount})が進めた期の回数(${clicks})と一致しない`);

  const areaVisible = await page.evaluate(() => document.getElementById("turnProgressArea").style.display);
  assert.equal(areaVisible, "none", "gameOver時は通常の進行UI(turnProgressArea)が隠れているべき");

  log(`[pattern2] business=${business} ${clicks}回の期進行でcrisis遷移: OK（撤退バッジ履歴: ${JSON.stringify(withdrawBadgeHistory)}）`);
  return { business, clicks, go };
}

/**
 * やり直し(#restartGameBtn)の検証。gameOver画面（パターン②到達後の状態を再利用）から
 * 「最初からやり直す」を押し、期の進行状態（turn/history/criticalStreak/gameOver）だけが
 * リセットされ、店舗・業種のセットアップはやり直されない（restartTurnProgression()の仕様）
 * ことを確認する。
 */
async function runRestartCheck(page, log) {
  const go = await gameOverInfo(page);
  assert.equal(go.visible, true, "やり直し検証はgameOver画面から始める想定");

  await page.click("#restartGameBtn");
  await page.waitForFunction(() => document.getElementById("gameOverScreen").style.display === "none", { timeout: 10000 });

  const goAfter = await gameOverInfo(page);
  assert.equal(goAfter.visible, false, "やり直し後はgameOverScreenが隠れるべき");

  const label = await currentTurnLabel(page);
  assert.equal(label, "現在", "やり直し後は進行バーが「現在」（turn=0）に戻るべき");

  const histCount = await turnHistoryCount(page);
  assert.equal(histCount, 0, "やり直し後はturnHistoryListが空になるべき");

  const areaVisible = await page.evaluate(() => document.getElementById("turnProgressArea").style.display);
  assert.notEqual(areaVisible, "none", "やり直し後は通常の進行UI(turnProgressArea)が再び表示されるべき");

  // 経営判断はrestartTurnProgression()でnullに戻るため、選び直すまでadvanceTurnBtnはdisabledのはず。
  const disabledBeforeChoice = await page.evaluate(() => document.getElementById("advanceTurnBtn").disabled);
  assert.equal(disabledBeforeChoice, true, "やり直し直後、経営判断を選ぶ前はadvanceTurnBtnがdisabledのはず");

  await selectDecision(page, "maintain");
  const disabledAfterChoice = await page.evaluate(() => document.getElementById("advanceTurnBtn").disabled);
  assert.equal(disabledAfterChoice, false, "やり直し後に経営判断を選べば、advanceTurnBtnは再び押せるようになるはず");

  log("[restart] gameOver後のやり直しで進行状態がリセットされる: OK");
}

/**
 * パターン③: 途中撤退 → withdraw遷移。
 * 「現在」（turn=0）の時点で「E. 撤退する」を選んで期を進める。advanceTurnBtnのクリック
 * ハンドラは managementDecision === "withdraw" を診断信号(sig)と無関係に無条件で判定するため、
 * 業種・エリアの相性やcarryoverEffectの状態にかかわらず必ず即座にgameOver(reason=withdraw)へ
 * 遷移する。
 */
async function runPatternWithdraw(page, baseUrl, areaName, log) {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  const business = await firstBusinessId(page);
  await verifyZeroSetupStart({ page, baseUrl, areaName, business, log });

  assert.equal(await currentTurnLabel(page), "現在", "撤退検証は開始直後（現在＝turn0）から行う");
  assert.equal(await turnHistoryCount(page), 0);

  await selectDecision(page, "withdraw");
  const disabled = await page.evaluate(() => document.getElementById("advanceTurnBtn").disabled);
  assert.equal(disabled, false, "撤退を選べばadvanceTurnBtnは押せるはず（turn0はTURN_CHECKPOINTSの最後ではない）");

  await clickAdvanceAndWait(page);

  const go = await gameOverInfo(page);
  assert.equal(go.visible, true, "撤退を選んで期を進めたのにgameOverにならなかった");
  assert.equal(go.reason, "withdraw", `gameOverの理由が想定と違う: ${JSON.stringify(go)}`);
  assert.ok(go.text.includes("（現在時点）"), `撤退時点のラベルが「現在」（turn0）になっていない: ${go.text}`);

  const histCount = await turnHistoryCount(page);
  assert.equal(histCount, 1, "撤退はturn0の1回の期進行でgameOverになるはずなので、履歴は1件のはず");

  log(`[pattern3] business=${business} turn0での撤退選択で即座にwithdraw遷移: OK`);
}

async function main() {
  const tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), "ss01s04-6-e2e-"));
  const port = 18280 + (process.pid % 700);
  const baseUrl = `http://127.0.0.1:${port}/`;
  const server = await startStaticServer(REPO_ROOT, port);

  const browser = await chromium.launch();
  let failures = 0;
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const consoleErrors = [];
    page.on("pageerror", (err) => consoleErrors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    const pkgCache = resolvePkgCache(path.join(REPO_ROOT, "node_modules"));
    for (const [k, p] of Object.entries(pkgCache)) {
      assert.ok(fssync.existsSync(p), `fixture dependency missing: ${k} (${p}). Run "npm install" first.`);
    }
    await installMockRoutes(page, { pkgCache });

    const areaName = await packagedAreaName();

    await runPatternGoodEnding(page, baseUrl, areaName, (...a) => console.log("[test]", ...a));
    const { go: crisisGo } = await runPatternCrisis(page, baseUrl, areaName, (...a) => console.log("[test]", ...a));
    assert.equal(crisisGo.reason, "crisis");
    await runRestartCheck(page, (...a) => console.log("[test]", ...a));
    await runPatternWithdraw(page, baseUrl, areaName, (...a) => console.log("[test]", ...a));

    // favicon/タイル画像のロードエラーは本題と無関係のため無視する（generate_area_data.test.mjsと同じ扱い）。
    const seriousErrors = consoleErrors.filter(
      (m) => !/tile\.openstreetmap|net::ERR_|404 \(Not Found\)/.test(m)
    );
    assert.equal(seriousErrors.length, 0, `unexpected console/page errors: ${JSON.stringify(seriousErrors)}`);

    console.log("[test] ALL PASSED");
  } catch (e) {
    failures++;
    console.error("[test] FAILED:", e);
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
    await fs.rm(tmpRoot, { recursive: true, force: true });
  }

  if (failures > 0) {
    console.error(`[test] ${failures} failure(s).`);
    process.exitCode = 1;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
