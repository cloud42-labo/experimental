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
