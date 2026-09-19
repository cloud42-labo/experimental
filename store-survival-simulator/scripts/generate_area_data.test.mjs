#!/usr/bin/env node
/**
 * generate_area_data.mjs のオフライン回帰テスト。
 *
 * 実際のESTAT_APP_ID・実ネットワーク（unpkg.com / api.e-stat.go.jp）は使わない。
 * Leaflet/Turf本体はローカルのdevDependency、e-Stat応答はダミーfixtureに差し替え、
 * ブラウザ操作の骨格（ダイアログ処理・ダウンロード捕捉・index.json更新・
 * ゼロセットアップ起動確認）だけを検証する。secretsが無いCIやローカルでも実行できる。
 *
 * 使い方: node scripts/generate_area_data.test.mjs
 */
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs/promises";
import fssync from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

import { generateAreaData, verifyZeroSetupStart } from "./generate_area_data.mjs";
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

async function main() {
  const tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), "ss01s01-3-test-"));
  const appDir = path.join(tmpRoot, "app");
  const outDir = path.join(appDir, "data", "areas");

  // index.html + data/areas/README.md だけをテスト用に複製する（本番ディレクトリは変更しない）。
  await fs.mkdir(path.join(appDir, "data", "areas"), { recursive: true });
  await fs.copyFile(path.join(REPO_ROOT, "index.html"), path.join(appDir, "index.html"));

  const port = 18080 + (process.pid % 1000);
  const baseUrl = `http://127.0.0.1:${port}/`;
  const server = await startStaticServer(appDir, port);

  const browser = await chromium.launch();
  let failures = 0;
  try {
    const context = await browser.newContext({ acceptDownloads: true });
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

    await page.goto(baseUrl, { waitUntil: "domcontentloaded" });

    const result = await generateAreaData({
      page,
      appId: "TEST-DUMMY-APP-ID",
      location: "35.681236,139.767125",
      name: "テスト用エリア（東京駅周辺）",
      business: "conveni",
      outDir,
      timeoutMs: 60000,
      log: (...a) => console.log("[test]", ...a)
    });

    // index.html downloadAreaPack()のスラッグ化ロジックは全角括弧を除去する（実装通りの挙動）。
    assert.equal(result.file, "テスト用エリア東京駅周辺.json");
    assert.ok(result.meshCount > 0, "meshCount should be > 0");
    assert.ok(fssync.existsSync(result.destPath), "area json file should exist");
    assert.ok(fssync.existsSync(result.indexPath), "index.json should exist");

    const indexJson = JSON.parse(await fs.readFile(result.indexPath, "utf-8"));
    assert.equal(indexJson.areas.length, 1);
    assert.equal(indexJson.areas[0].file, result.file);
    assert.equal(indexJson.areas[0].mesh_count, result.meshCount);

    const pack = JSON.parse(await fs.readFile(result.destPath, "utf-8"));
    assert.equal(pack.schema_version, 1);
    assert.equal(typeof pack.store.lat, "number");
    assert.equal(typeof pack.store.lng, "number");

    console.log("[test] generateAreaData: OK");

    // 同名で再実行しても index.json が重複登録されないこと（冪等性）。
    // 1回目でゲーム画面へ遷移しているため、起動画面から取り直す。
    await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
    const result2 = await generateAreaData({
      page,
      appId: "TEST-DUMMY-APP-ID",
      location: "35.681236,139.767125",
      name: "テスト用エリア（東京駅周辺）",
      business: "conveni",
      outDir,
      timeoutMs: 60000,
      log: () => {}
    });
    const indexJson2 = JSON.parse(await fs.readFile(result2.indexPath, "utf-8"));
    assert.equal(indexJson2.areas.length, 1, "re-generating the same area name must not duplicate index.json entries");
    console.log("[test] idempotent re-generation: OK");

    // ゼロセットアップ起動フロー: エリア選択だけでゲーム画面に到達できること。
    await verifyZeroSetupStart({
      page,
      baseUrl,
      areaName: "テスト用エリア（東京駅周辺）",
      business: "conveni",
      log: (...a) => console.log("[test]", ...a)
    });
    console.log("[test] verifyZeroSetupStart: OK");

    // favicon.ico の404やタイル画像の読み込みエラーはテストの本題と無関係のため無視する。
    const seriousErrors = consoleErrors.filter(
      (m) => !/tile\.openstreetmap|net::ERR_|404 \(Not Found\)/.test(m)
    );
    assert.equal(seriousErrors.length, 0, `unexpected console/page errors: ${JSON.stringify(seriousErrors)}`);
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
  } else {
    console.log("[test] ALL PASSED");
  }
}

main();
