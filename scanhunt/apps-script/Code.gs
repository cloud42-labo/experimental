/**
 * Scanhunt Apps Script API【SH-02-S03】
 *
 * PWAから画像URL・AI解析結果・商品マスターをGoogle Spreadsheetへ保存するための
 * Web App API。仕様の詳細・デプロイ手順は scanhunt/docs/apps-script-api.md を参照。
 *
 * 前提: このスクリプトは SH-02-S01 で作成される Spreadsheet に束縛する
 * （コンテナバインドスクリプト）。Products / ScanHistory / ProductImages / AIJobs の
 * 4シート（scanhunt/docs/spreadsheet-columns.md）が既に初期化されていること。
 */

// ===== 設定 =====

var SHEET_NAMES = {
  PRODUCTS: 'Products',
  SCAN_HISTORY: 'ScanHistory',
  PRODUCT_IMAGES: 'ProductImages',
  AI_JOBS: 'AIJobs'
};

// gtin_jan等、先頭ゼロが消えると事故になる列。書き込み時にプレーンテキスト書式を強制する。
// （spreadsheet-columns.md 実装上の必須ルール#1）
 var PLAIN_TEXT_COLUMNS = ['gtin_jan', 'parent_gtin', 'gpc_brick_code', 'lot_number', 'manufacturer_part_number'];

// raw_responseのセル上限（spreadsheet-columns.md AIJobs節）
var RAW_RESPONSE_CELL_LIMIT = 50000;

// ===== エントリーポイント =====

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      throw new ApiError('bad_request', 'リクエストボディがありません。');
    }
    var body = JSON.parse(e.postData.contents);
    checkApiKey_(body.apiKey);

    var action = body.action;
    var data = body.data || {};
    var result;

    switch (action) {
      case 'createScanHistory':
        result = createScanHistory_(data);
        break;
      case 'updateScanHistory':
        result = updateScanHistory_(data);
        break;
      case 'createProductImage':
        result = createProductImage_(data);
        break;
      case 'createAIJob':
        result = createAIJob_(data);
        break;
      case 'findProductByGtin':
        result = findProductByGtin_(data);
        break;
      case 'upsertProduct':
        result = upsertProduct_(data);
        break;
      case 'resolveProductId':
        result = resolveProductId_(data);
        break;
      default:
        throw new ApiError('unknown_action', 'action "' + action + '" は未対応です。');
    }

    return jsonOutput_({ success: true, data: result });
  } catch (err) {
    return jsonOutput_(errorToResponse_(err));
  }
}

// GETはデプロイ確認用のヘルスチェックのみ。データ操作はPOSTのみ受け付ける。
function doGet(e) {
  return jsonOutput_({ success: true, data: { status: 'ok', service: 'scanhunt-apps-script-api' } });
}

// ===== APIキー =====
// Apps Script WebアプリはCORSプリフライトの都合上カスタムヘッダーを扱いにくいため、
// リクエストボディの apiKey フィールドで認証する（詳細: docs/secrets-and-config.md）。
function checkApiKey_(apiKey) {
  var expected = PropertiesService.getScriptProperties().getProperty('API_KEY');
  if (!expected) {
    // API_KEY未設定はデプロイミス。安全側に倒して常に拒否する。
    throw new ApiError('server_misconfigured', 'API_KEYがScript Propertiesに設定されていません。');
  }
  if (apiKey !== expected) {
    throw new ApiError('unauthorized', 'APIキーが一致しません。');
  }
}

// ===== 各アクション =====
// 「紐付けの順序」6ステップ（product-images-and-ai-jobs.md）に対応する:
//   1. createScanHistory（作成時点ではfinal_status未確定。updateScanHistoryで後日確定する）
//   2. createProductImage×2  3-4. createAIJob（リトライ毎）
//   5. findProductByGtin → upsertProduct  6. resolveProductId
//
// createScanHistory/createProductImage/createAIJobはいずれも、同一の主キー（scan_id/
// image_id/job_id）が既にシートにあれば新規行を追加せず既存の値を返す（べき等化）。
// PWAがネットワークエラー・タイムアウトで応答を受け取れず再送した場合に、行が重複したり
// attempt_noが飛んだりするのを防ぐため。

function createScanHistory_(data) {
  requireFields_(data, ['scan_id', 'scanned_at']);
  var sheet = getSheet_(SHEET_NAMES.SCAN_HISTORY);
  var headerMap = getHeaderMap_(sheet);
  if (findRowIndexByColumnValue_(sheet, headerMap, 'scan_id', data.scan_id)) {
    return { scan_id: data.scan_id };
  }
  // final_status（試行全体の結末）は撮影直後の時点ではまだ分からない。ここではpendingで
  // 作成し、AI解析の試行が出揃った時点でPWAがupdateScanHistoryで確定させる。
  var row = Object.assign(
    { final_status: 'pending' },
    data,
    { created_at: data.created_at || nowIso_() }
  );
  appendRowByHeader_(sheet, row);
  return { scan_id: data.scan_id };
}

// AI解析の試行（リトライ含む）が出揃い、final_status等の「試行全体の結末」が確定した時点で
// PWAが呼ぶ。ScanHistoryはproduct_id以外は追記専用としてきたが、final_status（と付随する
// attempt_count/best_job_id/duration_total_ms等）は撮影時点では確定しない値であるため、
// resolveProductIdのproduct_id後追い更新と同じ仕組みで後追い更新する。
function updateScanHistory_(data) {
  requireFields_(data, ['scan_id']);
  var patch = Object.assign({}, data);
  delete patch.scan_id;
  return updateFirstByColumnValue_(SHEET_NAMES.SCAN_HISTORY, 'scan_id', data.scan_id, patch);
}

function createProductImage_(data) {
  requireFields_(data, ['image_id', 'scan_id', 'face', 'drive_file_id', 'storage_path', 'captured_at', 'mime_type']);
  var sheet = getSheet_(SHEET_NAMES.PRODUCT_IMAGES);
  var headerMap = getHeaderMap_(sheet);
  if (findRowIndexByColumnValue_(sheet, headerMap, 'image_id', data.image_id)) {
    return { image_id: data.image_id };
  }
  var now = nowIso_();
  var row = Object.assign(
    { label_status: 'ai_only', is_training_candidate: true },
    data,
    { created_at: data.created_at || now, updated_at: now }
  );
  appendRowByHeader_(sheet, row);
  return { image_id: data.image_id };
}

function createAIJob_(data) {
  requireFields_(data, [
    'job_id', 'scan_id', 'job_type', 'input_image_ids',
    'ai_model', 'prompt_version', 'schema_version', 'status', 'started_at'
  ]);
  var sheet = getSheet_(SHEET_NAMES.AI_JOBS);
  var headerMap = getHeaderMap_(sheet);
  var existingRow = findRowIndexByColumnValue_(sheet, headerMap, 'job_id', data.job_id);
  if (existingRow) {
    // 同一job_idの再送はattempt_noを再採番せず、既に確定した値をそのまま返す。
    var existing = readRow_(sheet, headerMap, existingRow);
    return { job_id: data.job_id, attempt_no: existing.attempt_no };
  }
  var now = nowIso_();

  var row = Object.assign({}, data);
  // attempt_noはjob_typeをまたいでリセットしない通し番号のため、クライアント値は使わず
  // サーバー側で「その scan_id の既存AIJobs最大値+1」を採番する（積み残し#4への対応、
  // product-images-and-ai-jobs.md「attempt_noの採番規則」）。
  row.attempt_no = getNextAttemptNo_(data.scan_id);
  row.input_image_ids = arrayToCsv_(data.input_image_ids);
  row.validation_failures = arrayToCsv_(data.validation_failures);

  var raw = data.raw_response;
  if (typeof raw === 'string' && raw.length > RAW_RESPONSE_CELL_LIMIT) {
    row.raw_response = raw.slice(0, RAW_RESPONSE_CELL_LIMIT);
    row.raw_response_truncated = true;
    saveFullRawResponseToDrive_(data.job_id, raw);
  } else {
    row.raw_response_truncated = false;
  }
  row.created_at = data.created_at || now;

  appendRowByHeader_(sheet, row);
  return { job_id: data.job_id, attempt_no: row.attempt_no };
}

function getNextAttemptNo_(scanId) {
  if (!scanId) throw new ApiError('missing_fields', '必須フィールドが不足しています: scan_id');
  var sheet = getSheet_(SHEET_NAMES.AI_JOBS);
  var headerMap = getHeaderMap_(sheet);
  var scanCol = headerMap['scan_id'];
  var attemptCol = headerMap['attempt_no'];
  var lastRow = sheet.getLastRow();
  var max = 0;
  if (lastRow >= 2) {
    var values = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();
    values.forEach(function (r) {
      if (String(r[scanCol - 1]) === String(scanId)) {
        var n = Number(r[attemptCol - 1]) || 0;
        if (n > max) max = n;
      }
    });
  }
  return max + 1;
}

// GTINで既存Productsを検索する（紐付けの順序 step 5 の前段）。マージ済み行は除外する。
function findProductByGtin_(data) {
  requireFields_(data, ['gtin_jan']);
  var sheet = getSheet_(SHEET_NAMES.PRODUCTS);
  var headerMap = getHeaderMap_(sheet);
  var rowIndex = findRowIndexByColumnValue_(sheet, headerMap, 'gtin_jan', data.gtin_jan);
  if (!rowIndex) return { found: false, product: null };
  var product = readRow_(sheet, headerMap, rowIndex);
  if (product.record_status === 'merged') return { found: false, product: null };
  return { found: true, product: product };
}

// Products行を新規作成、または既存行を更新する（product_idが既存なら更新、無ければ新規作成）。
// 更新時はrevisionを+1する（spreadsheet-columns.md メタ列の方針）。
function upsertProduct_(data) {
  requireFields_(data, ['product_id', 'gtin_status']);
  var sheet = getSheet_(SHEET_NAMES.PRODUCTS);
  var headerMap = getHeaderMap_(sheet);
  var now = nowIso_();

  var existingRow = findRowIndexByColumnValue_(sheet, headerMap, 'product_id', data.product_id);

  if (existingRow) {
    var current = readRow_(sheet, headerMap, existingRow);
    var merged = Object.assign({}, current, data);
    merged.revision = (Number(current.revision) || 0) + 1;
    merged.revision_reason = data.revision_reason || 'rescan';
    merged.updated_at = now;
    writeRow_(sheet, headerMap, existingRow, merged);
    return { product_id: data.product_id, revision: merged.revision, created: false };
  }

  var row = Object.assign(
    { revision: 1, revision_reason: 'initial', record_status: 'active', first_scanned_at: now },
    data,
    { created_at: now, updated_at: now }
  );
  appendRowByHeader_(sheet, row);
  return { product_id: data.product_id, revision: 1, created: true };
}

// GTIN確定後、ScanHistory/ProductImages/AIJobsのproduct_idを後追いで更新する
// （product-images-and-ai-jobs.md「紐付けの順序」step 6）。
function resolveProductId_(data) {
  requireFields_(data, ['scan_id', 'product_id']);
  var patch = { product_id: data.product_id, updated_at: nowIso_() };
  return {
    scan_history: updateFirstByColumnValue_(SHEET_NAMES.SCAN_HISTORY, 'scan_id', data.scan_id, { product_id: data.product_id }),
    product_images: updateAllByColumnValue_(SHEET_NAMES.PRODUCT_IMAGES, 'scan_id', data.scan_id, patch),
    ai_jobs: updateAllByColumnValue_(SHEET_NAMES.AI_JOBS, 'scan_id', data.scan_id, { product_id: data.product_id })
  };
}

// ===== 内部セルフテストハーネス【SH-02-S03-T02-A】 =====
//
// 7 action（createScanHistory / updateScanHistory / createProductImage / createAIJob /
// findProductByGtin / upsertProduct / resolveProductId）を、実際にバインドされている
// Spreadsheetへ対して動かして検証する。
//
// 実行方法: Apps Scriptエディタで本ファイルを開き、関数選択で `runSelfTest` を選び
// 実行する（実行 > 実行）。結果は「実行ログ」に出力される。
//
// 設計上の制約:
//   - doPost/doGetのactionディスパッチには一切接続しない。Web App経由（HTTP）で
//     外部から起動できる経路を作らないことで、Script Properties（API_KEY/
//     SPREADSHEET_ID）が外部に露出する余地を作らない。
//   - 出力はPASS/FAILのsanitized summaryのみ。redactSecrets_() で、万一メッセージに
//     Script Propertiesの値そのものが混入してもログ出力前に必ず置換する。
//   - テストデータは全て SELF_TEST_PREFIX_ を先頭に持つ識別可能なIDを使う
//     （gtin_janのみ例外。プレーンテキスト書式検証のため純粋な数字文字列にする必要が
//     あり、代わりに同じ行のproduct_idにprefixを持たせてcleanupの対象にする）。
//   - 実行前後で cleanupSelfTestData_() を必ず呼び、成功・失敗を問わずテストデータを
//     残さない（try/finally）。
//   - 本Taskの範囲は「コードとして完結するセルフテストハーネスの実装」まで。実際の
//     Spreadsheet/Web App環境に対する実行そのもの（動作確認）は範囲外
//     （apps-script-api.md の「動作確認チェックリスト」でHumanが別途実施する）。

var SELF_TEST_PREFIX_ = '__selftest__';

function runSelfTest() {
  var results = [];
  var ids = makeSelfTestIds_();
  var cleanup;
  try {
    // 前回の実行がエラー等でcleanupまで到達できなかった場合の残骸を先に掃除する。
    cleanupSelfTestData_();
    runSelfTestSteps_(results, ids);
  } catch (err) {
    results.push(selfTestResult_('unexpected_error', false, sanitizeMessage_(err)));
  } finally {
    try {
      cleanup = cleanupSelfTestData_();
    } catch (cleanupErr) {
      cleanup = { error: sanitizeMessage_(cleanupErr) };
    }
  }
  var summary = buildSelfTestSummary_(results, cleanup);
  Logger.log(JSON.stringify(summary, null, 2));
  return summary;
}

function makeSelfTestIds_() {
  var runId = SELF_TEST_PREFIX_ + Utilities.getUuid();
  return {
    scanId: runId + '__scan',
    imageIdFront: runId + '__img_front',
    imageIdBack: runId + '__img_back',
    jobId1: runId + '__job1',
    jobId2: runId + '__job2',
    productId: runId + '__product',
    // gtin_jan列は純粋な数字文字列でなければプレーンテキスト書式（先頭ゼロ保持）の
    // 検証にならないため、識別可能prefixは付けない（cleanupはproduct_id側で行う）。
    // 実在GTINと衝突しないよう、末尾に実行毎の乱数を持たせる。
    gtinJan: '0' + (990000000000 + Math.floor(Math.random() * 9999999))
  };
}

function runSelfTestSteps_(results, ids) {
  var scanHistorySheet = getSheet_(SHEET_NAMES.SCAN_HISTORY);
  var scanHistoryHeaders = getHeaderMap_(scanHistorySheet);

  // --- createScanHistory: 反映・final_status初期値・プレーンテキスト保持 ---
  var scannedAt = nowIso_();
  createScanHistory_({ scan_id: ids.scanId, scanned_at: scannedAt });
  var scanRowIndex = findRowIndexByColumnValue_(scanHistorySheet, scanHistoryHeaders, 'scan_id', ids.scanId);
  var createdScan = scanRowIndex ? readRow_(scanHistorySheet, scanHistoryHeaders, scanRowIndex) : null;
  results.push(selfTestResult_(
    'createScanHistory: ScanHistoryへ反映され、final_status初期値がpending',
    !!createdScan && createdScan.final_status === 'pending' && !!createdScan.created_at
  ));

  var createdAtCell = scanRowIndex ? scanHistorySheet.getRange(scanRowIndex, scanHistoryHeaders['created_at']) : null;
  results.push(selfTestResult_(
    'createScanHistory: created_at列（_at終わり）がプレーンテキスト書式',
    !!createdAtCell && createdAtCell.getNumberFormat() === '@'
  ));

  // --- createScanHistory: べき等性 ---
  createScanHistory_({ scan_id: ids.scanId, scanned_at: scannedAt });
  results.push(selfTestResult_(
    'createScanHistory: 同一scan_idの再送で行が重複しない（べき等）',
    countRowsByColumnValue_(scanHistorySheet, scanHistoryHeaders, 'scan_id', ids.scanId) === 1
  ));

  // --- updateScanHistory: 後追い更新の反映（新規行を作らない） ---
  updateScanHistory_({ scan_id: ids.scanId, final_status: 'success', attempt_count: 2, best_job_id: ids.jobId2, duration_total_ms: 4321 });
  var updatedScanRowIndex = findRowIndexByColumnValue_(scanHistorySheet, scanHistoryHeaders, 'scan_id', ids.scanId);
  var updatedScan = readRow_(scanHistorySheet, scanHistoryHeaders, updatedScanRowIndex);
  results.push(selfTestResult_(
    'updateScanHistory: final_status/attempt_count/best_job_idが反映され新規行を作らない',
    updatedScan.final_status === 'success' &&
      Number(updatedScan.attempt_count) === 2 &&
      updatedScan.best_job_id === ids.jobId2 &&
      countRowsByColumnValue_(scanHistorySheet, scanHistoryHeaders, 'scan_id', ids.scanId) === 1
  ));

  // --- createProductImage×2: 反映・デフォルト値 ---
  var imageSheet = getSheet_(SHEET_NAMES.PRODUCT_IMAGES);
  var imageHeaders = getHeaderMap_(imageSheet);
  var capturedAt = nowIso_();
  createProductImage_({
    image_id: ids.imageIdFront, scan_id: ids.scanId, face: 'front',
    drive_file_id: ids.imageIdFront + '_drive', storage_path: 'unresolved/' + ids.scanId + '/front.jpg',
    captured_at: capturedAt, mime_type: 'image/jpeg'
  });
  createProductImage_({
    image_id: ids.imageIdBack, scan_id: ids.scanId, face: 'back',
    drive_file_id: ids.imageIdBack + '_drive', storage_path: 'unresolved/' + ids.scanId + '/back.jpg',
    captured_at: capturedAt, mime_type: 'image/jpeg'
  });
  var frontRow = readRow_(imageSheet, imageHeaders, findRowIndexByColumnValue_(imageSheet, imageHeaders, 'image_id', ids.imageIdFront));
  results.push(selfTestResult_(
    'createProductImage: ProductImagesへ反映され、省略時デフォルト（label_status=ai_only等）が入る',
    frontRow.label_status === 'ai_only' && String(frontRow.is_training_candidate) === 'TRUE'
  ));

  // --- createProductImage: べき等性 ---
  createProductImage_({
    image_id: ids.imageIdFront, scan_id: ids.scanId, face: 'front',
    drive_file_id: 'ignored', storage_path: 'ignored', captured_at: capturedAt, mime_type: 'image/jpeg'
  });
  results.push(selfTestResult_(
    'createProductImage: 同一image_idの再送で行が重複しない（べき等）',
    countRowsByColumnValue_(imageSheet, imageHeaders, 'image_id', ids.imageIdFront) === 1
  ));

  // --- createAIJob: attempt_noの自動採番（scan_id単位で1, 2） ---
  var jobSheet = getSheet_(SHEET_NAMES.AI_JOBS);
  var jobHeaders = getHeaderMap_(jobSheet);
  var job1 = createAIJob_({
    job_id: ids.jobId1, scan_id: ids.scanId, job_type: 'initial',
    input_image_ids: [ids.imageIdFront, ids.imageIdBack], ai_model: 'selftest-model',
    prompt_version: 'selftest', schema_version: 'selftest', status: 'success', started_at: nowIso_()
  });
  var job2 = createAIJob_({
    job_id: ids.jobId2, scan_id: ids.scanId, job_type: 'retry',
    input_image_ids: [ids.imageIdFront, ids.imageIdBack], ai_model: 'selftest-model',
    prompt_version: 'selftest', schema_version: 'selftest', status: 'success', started_at: nowIso_()
  });
  results.push(selfTestResult_(
    'createAIJob: attempt_noがscan_id単位で1, 2と自動採番される',
    Number(job1.attempt_no) === 1 && Number(job2.attempt_no) === 2
  ));

  // --- createAIJob: べき等性（再送してもattempt_noを再採番しない） ---
  var job1Resend = createAIJob_({
    job_id: ids.jobId1, scan_id: ids.scanId, job_type: 'initial',
    input_image_ids: [ids.imageIdFront], ai_model: 'selftest-model',
    prompt_version: 'selftest', schema_version: 'selftest', status: 'success', started_at: nowIso_()
  });
  results.push(selfTestResult_(
    'createAIJob: 同一job_idの再送でattempt_noを再採番せず行も重複しない（べき等）',
    Number(job1Resend.attempt_no) === 1 &&
      countRowsByColumnValue_(jobSheet, jobHeaders, 'job_id', ids.jobId1) === 1
  ));

  // --- findProductByGtin（未登録） ---
  var notFound = findProductByGtin_({ gtin_jan: ids.gtinJan });
  results.push(selfTestResult_(
    'findProductByGtin: 未登録gtin_janに対しfound=falseを返す',
    notFound.found === false && notFound.product === null
  ));

  // --- upsertProduct: 新規作成（revision=1） ---
  var upsertCreate = upsertProduct_({
    product_id: ids.productId, gtin_status: 'confirmed', gtin_jan: ids.gtinJan,
    product_name: SELF_TEST_PREFIX_ + ' product'
  });
  results.push(selfTestResult_(
    'upsertProduct: 新規product_idでrevision=1として作成される',
    upsertCreate.created === true && Number(upsertCreate.revision) === 1
  ));

  // --- findProductByGtin（登録後） ---
  var found = findProductByGtin_({ gtin_jan: ids.gtinJan });
  results.push(selfTestResult_(
    'findProductByGtin: upsertProduct後はfound=trueで該当product_idを返す',
    found.found === true && found.product && found.product.product_id === ids.productId
  ));

  // --- upsertProduct: gtin_janのプレーンテキスト保持（先頭ゼロ） ---
  var productSheet = getSheet_(SHEET_NAMES.PRODUCTS);
  var productHeaders = getHeaderMap_(productSheet);
  var productRowIndex = findRowIndexByColumnValue_(productSheet, productHeaders, 'product_id', ids.productId);
  var gtinCell = productSheet.getRange(productRowIndex, productHeaders['gtin_jan']);
  results.push(selfTestResult_(
    'upsertProduct: gtin_janがプレーンテキスト書式で先頭ゼロを保持する',
    gtinCell.getNumberFormat() === '@' && String(gtinCell.getValue()) === ids.gtinJan
  ));

  // --- upsertProduct: 既存行の更新（revision+1） ---
  var upsertUpdate = upsertProduct_({
    product_id: ids.productId, gtin_status: 'confirmed', gtin_jan: ids.gtinJan,
    product_name: SELF_TEST_PREFIX_ + ' product updated'
  });
  results.push(selfTestResult_(
    'upsertProduct: 既存product_idの更新でrevisionが+1される',
    upsertUpdate.created === false && Number(upsertUpdate.revision) === 2
  ));

  // --- resolveProductId: ScanHistory/ProductImages(×2)/AIJobs(×2)へ後追い反映 ---
  resolveProductId_({ scan_id: ids.scanId, product_id: ids.productId });
  var scanAfter = readRow_(scanHistorySheet, scanHistoryHeaders, findRowIndexByColumnValue_(scanHistorySheet, scanHistoryHeaders, 'scan_id', ids.scanId));
  var frontAfter = readRow_(imageSheet, imageHeaders, findRowIndexByColumnValue_(imageSheet, imageHeaders, 'image_id', ids.imageIdFront));
  var backAfter = readRow_(imageSheet, imageHeaders, findRowIndexByColumnValue_(imageSheet, imageHeaders, 'image_id', ids.imageIdBack));
  var job1After = readRow_(jobSheet, jobHeaders, findRowIndexByColumnValue_(jobSheet, jobHeaders, 'job_id', ids.jobId1));
  var job2After = readRow_(jobSheet, jobHeaders, findRowIndexByColumnValue_(jobSheet, jobHeaders, 'job_id', ids.jobId2));
  results.push(selfTestResult_(
    'resolveProductId: ScanHistory・ProductImages（2行）・AIJobs（2行）全てにproduct_idが反映される',
    scanAfter.product_id === ids.productId &&
      frontAfter.product_id === ids.productId &&
      backAfter.product_id === ids.productId &&
      job1After.product_id === ids.productId &&
      job2After.product_id === ids.productId
  ));
}

// ===== セルフテスト用ヘルパー =====

function countRowsByColumnValue_(sheet, headerMap, columnName, value) {
  var col = headerMap[columnName];
  if (!col) return 0;
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return 0;
  var values = sheet.getRange(2, col, lastRow - 1, 1).getValues();
  var count = 0;
  for (var i = 0; i < values.length; i++) {
    if (String(values[i][0]) === String(value)) count++;
  }
  return count;
}

// prefix一致する行を末尾から削除する（先頭から消すと行番号がズレるため）。
function deleteRowsByPrefix_(sheetName, columnName, prefix) {
  var sheet = getSheet_(sheetName);
  var headerMap = getHeaderMap_(sheet);
  var col = headerMap[columnName];
  if (!col) return 0;
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return 0;
  var values = sheet.getRange(2, col, lastRow - 1, 1).getValues();
  var deleted = 0;
  for (var i = values.length - 1; i >= 0; i--) {
    if (String(values[i][0]).indexOf(prefix) === 0) {
      sheet.deleteRow(i + 2);
      deleted++;
    }
  }
  return deleted;
}

function cleanupSelfTestData_() {
  return {
    scan_history: deleteRowsByPrefix_(SHEET_NAMES.SCAN_HISTORY, 'scan_id', SELF_TEST_PREFIX_),
    product_images: deleteRowsByPrefix_(SHEET_NAMES.PRODUCT_IMAGES, 'image_id', SELF_TEST_PREFIX_),
    ai_jobs: deleteRowsByPrefix_(SHEET_NAMES.AI_JOBS, 'job_id', SELF_TEST_PREFIX_),
    products: deleteRowsByPrefix_(SHEET_NAMES.PRODUCTS, 'product_id', SELF_TEST_PREFIX_)
  };
}

function selfTestResult_(name, pass, detail) {
  var result = { name: name, pass: !!pass };
  if (detail) result.detail = sanitizeMessage_(detail);
  return result;
}

function buildSelfTestSummary_(results, cleanup) {
  var passed = results.filter(function (r) { return r.pass; }).length;
  var failed = results.length - passed;
  return {
    overall: (results.length > 0 && failed === 0) ? 'PASS' : 'FAIL',
    total: results.length,
    passed: passed,
    failed: failed,
    results: results,
    cleanup: cleanup
  };
}

// エラーメッセージにScript Propertiesの値（API_KEY/SPREADSHEET_ID）が万一混入していても
// ログ出力前に必ず置換する。「出力はsanitized summaryのみ」の担保。
function sanitizeMessage_(err) {
  var msg = (err && err.message) ? String(err.message) : String(err);
  return redactSecrets_(msg);
}

function redactSecrets_(text) {
  try {
    var props = PropertiesService.getScriptProperties();
    ['API_KEY', 'SPREADSHEET_ID'].forEach(function (key) {
      var val = props.getProperty(key);
      if (val && text.indexOf(val) !== -1) {
        text = text.split(val).join('[REDACTED]');
      }
    });
  } catch (e) {
    // Properties取得自体に失敗しても出力は止めない。
  }
  return text;
}

// ===== ヘッダー名ベースの読み書き =====
// 列インデックスを直書きせず、1行目のヘッダー名でマッピングする
// （spreadsheet-columns.md 実装上の必須ルール#2）。

// コンテナバインドスクリプトでも、Webアプリとして呼ばれた doPost/doGet の実行コンテキストでは
// エディタUIの「アクティブなスプレッドシート」が存在しないため SpreadsheetApp.getActiveSpreadsheet()
// は null を返しうる（Google Issue Tracker #189851066 等で報告済みの既知の挙動）。
// Script Properties に保存した自分自身の Spreadsheet ID を openById() で明示的に開く。
function getSpreadsheet_() {
  var id = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID');
  if (!id) {
    throw new ApiError('server_misconfigured', 'SPREADSHEET_IDがScript Propertiesに設定されていません。');
  }
  return SpreadsheetApp.openById(id);
}

function getSheet_(name) {
  var ss = getSpreadsheet_();
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    throw new ApiError('sheet_not_found', 'シート "' + name + '" が見つかりません。SH-02-S01のシート初期化を先に完了してください。');
  }
  return sheet;
}

function getHeaderMap_(sheet) {
  var lastCol = sheet.getLastColumn();
  if (lastCol === 0) {
    throw new ApiError('sheet_not_initialized', 'シート "' + sheet.getName() + '" にヘッダー行がありません。');
  }
  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  var map = {};
  headers.forEach(function (name, i) {
    if (name) map[String(name).trim()] = i + 1; // 1-based列番号
  });
  return map;
}

function appendRowByHeader_(sheet, dataObject) {
  var headerMap = getHeaderMap_(sheet);
  var lastCol = sheet.getLastColumn();
  var rowValues = new Array(lastCol).fill('');

  Object.keys(dataObject).forEach(function (key) {
    var col = headerMap[key];
    if (!col) return; // ヘッダーに無いキーは無視する（未知キー1つで書き込み全体を失敗させない）
    rowValues[col - 1] = normalizeValue_(dataObject[key]);
  });

  var newRow = sheet.getLastRow() + 1;
  sheet.getRange(newRow, 1, 1, lastCol).setValues([rowValues]);
  applyPlainTextFormat_(sheet, headerMap, newRow);
}

function readRow_(sheet, headerMap, rowIndex) {
  var lastCol = sheet.getLastColumn();
  var values = sheet.getRange(rowIndex, 1, 1, lastCol).getValues()[0];
  var obj = {};
  Object.keys(headerMap).forEach(function (name) {
    obj[name] = values[headerMap[name] - 1];
  });
  return obj;
}

function writeRow_(sheet, headerMap, rowIndex, dataObject) {
  var lastCol = sheet.getLastColumn();
  var current = sheet.getRange(rowIndex, 1, 1, lastCol).getValues()[0];
  Object.keys(dataObject).forEach(function (key) {
    var col = headerMap[key];
    if (!col) return;
    current[col - 1] = normalizeValue_(dataObject[key]);
  });
  sheet.getRange(rowIndex, 1, 1, lastCol).setValues([current]);
  applyPlainTextFormat_(sheet, headerMap, rowIndex);
}

function findRowIndexByColumnValue_(sheet, headerMap, columnName, value) {
  var col = headerMap[columnName];
  if (!col) throw new ApiError('unknown_column', '列 "' + columnName + '" が見つかりません。');
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return null;
  var values = sheet.getRange(2, col, lastRow - 1, 1).getValues();
  for (var i = 0; i < values.length; i++) {
    if (String(values[i][0]) === String(value)) return i + 2; // 実シート行番号
  }
  return null;
}

function updateFirstByColumnValue_(sheetName, keyColumn, keyValue, patch) {
  var sheet = getSheet_(sheetName);
  var headerMap = getHeaderMap_(sheet);
  var rowIndex = findRowIndexByColumnValue_(sheet, headerMap, keyColumn, keyValue);
  if (!rowIndex) return { updated: false, count: 0 };
  writeRow_(sheet, headerMap, rowIndex, patch);
  return { updated: true, count: 1 };
}

// ProductImages/AIJobsはscan_idにつき複数行あるため全件更新する
function updateAllByColumnValue_(sheetName, keyColumn, keyValue, patch) {
  var sheet = getSheet_(sheetName);
  var headerMap = getHeaderMap_(sheet);
  var col = headerMap[keyColumn];
  if (!col) throw new ApiError('unknown_column', '列 "' + keyColumn + '" が見つかりません。');
  var lastRow = sheet.getLastRow();
  var count = 0;
  if (lastRow >= 2) {
    var values = sheet.getRange(2, col, lastRow - 1, 1).getValues();
    for (var i = 0; i < values.length; i++) {
      if (String(values[i][0]) === String(keyValue)) {
        writeRow_(sheet, headerMap, i + 2, patch);
        count++;
      }
    }
  }
  return { updated: count > 0, count: count };
}

// gtin_jan等の先頭ゼロ事故を防ぐプレーンテキスト書式（#1）＋ 全ての `_at` 終わりの日時列・
// `expiry_date` にも同様に適用する（#3、シートロケールに引きずられるタイムゾーン事故の防止）。
function applyPlainTextFormat_(sheet, headerMap, rowIndex) {
  Object.keys(headerMap).forEach(function (name) {
    if (PLAIN_TEXT_COLUMNS.indexOf(name) !== -1 || /_at$/.test(name) || name === 'expiry_date') {
      sheet.getRange(rowIndex, headerMap[name]).setNumberFormat('@');
    }
  });
}

function normalizeValue_(value) {
  if (value === undefined || value === null) return '';
  if (Array.isArray(value)) return arrayToCsv_(value);
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE'; // チェックボックス型は使わない
  return value;
}

function arrayToCsv_(arr) {
  if (!arr) return '';
  if (typeof arr === 'string') return arr; // 既にCSV化済みならそのまま
  return arr.join(',');
}

// ===== raw_response全文保存 =====

function saveFullRawResponseToDrive_(jobId, rawResponse) {
  try {
    var folder = getOrCreateFolderPath_(['Scanhunt', 'logs']);
    var blob = Utilities.newBlob(rawResponse, 'application/json', jobId + '.json');
    folder.createFile(blob);
  } catch (err) {
    // ログ全文保存の失敗でジョブ記録自体を失敗させない。実行ログにのみ残す。
    Logger.log('raw_response全文のDrive保存に失敗しました: ' + err);
  }
}

function getOrCreateFolderPath_(pathParts) {
  var folder = DriveApp.getRootFolder();
  pathParts.forEach(function (part) {
    var it = folder.getFoldersByName(part);
    folder = it.hasNext() ? it.next() : folder.createFolder(part);
  });
  return folder;
}

// ===== 共通ユーティリティ =====

function requireFields_(data, fields) {
  var missing = fields.filter(function (f) {
    return data[f] === undefined || data[f] === null || data[f] === '';
  });
  if (missing.length > 0) {
    throw new ApiError('missing_fields', '必須フィールドが不足しています: ' + missing.join(', '));
  }
}

function nowIso_() {
  return Utilities.formatDate(new Date(), 'Asia/Tokyo', "yyyy-MM-dd'T'HH:mm:ssXXX");
}

function jsonOutput_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function errorToResponse_(err) {
  if (err instanceof ApiError) {
    return { success: false, error: { code: err.code, message: err.message } };
  }
  Logger.log(err && err.stack ? err.stack : err);
  return { success: false, error: { code: 'internal_error', message: String(err && err.message ? err.message : err) } };
}

function ApiError(code, message) {
  this.code = code;
  this.message = message;
}
ApiError.prototype = Object.create(Error.prototype);
ApiError.prototype.constructor = ApiError;
