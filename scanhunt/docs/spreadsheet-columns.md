# Google Spreadsheet 列設計（4シート・計167列）

由来: Notion `SH-01-S04｜Spreadsheet列設計`

[product-data-model.md](product-data-model.md)（90項目モデル）、
[product-images-and-ai-jobs.md](product-images-and-ai-jobs.md)、
[source-confidence-revision.md](source-confidence-revision.md) を、Google Spreadsheet の
**4シート・実列**へ落としたもの。実装はこの文書を見る。

| シート | 列数 | 1行が表すもの | 書き込み方 |
|---|---|---|---|
| `Products` | 111 | 商品1つ（GTIN単位） | 更新（`revision` を上げる） |
| `ScanHistory` | 16 | 撮影1回 | 追記 |
| `ProductImages` | 19 | 画像1枚 | 追記 |
| `AIJobs` | 21 | AI解析の試行1回 | 追記 |

`Products` だけが更新型で、残り3つは追記専用。**追記専用のシートには行の書き換えを行わない**
（`product_id` の後付け紐付けのみ例外）。

### JSONではなく実列にした理由

90項目を `data_json` のような1列に押し込む案は採らなかった。Spreadsheetを商品マスターDBとして
使う前提（`EPIC-SH-02`）と、CSV出力でそのままB2Bデータにする狙い（`SH-07-S01`）の両方が、
フラットな表であることに依存している。セル内JSONにすると、Spreadsheet上でのフィルタ・
並べ替え・目視確認がすべて成立しなくなる。

例外は `sources_json`・`confidence_json`・`other_nutrients` の3列のみ。いずれも**キーが可変**で
実列にできないもの。

---

## 実装上の必須ルール

設計と同じくらい、この4点を外すと動かない。

### 1. `gtin_jan` 列は「プレーンテキスト」書式にする

Spreadsheetは数字だけの文字列を数値へ自動変換する。**JANコードの先頭の `0` が消える**
（`04901234567890` → `4901234567890`）。8桁GTINでも同じ事故が起きる。シート初期化時に
`gtin_jan`・`parent_gtin`・`gpc_brick_code`・`lot_number`・`manufacturer_part_number` の各列へ
`setNumberFormat('@')` を適用する。

### 2. Apps Script は列インデックスではなくヘッダー名で読み書きする

1行目のヘッダーを読んで `{列名: インデックス}` のマップを作ってから操作する。列を追加・
並べ替えるたびにコードが壊れるのを防ぐ。90項目超の表では列番号の直書きは現実的でない。

### 3. 日時はISO 8601文字列で保存する

`captured_at`・`started_at` 等はすべて `2026-08-09T18:30:00+09:00` 形式の文字列。
Spreadsheetの日付型に任せるとタイムゾーンがシートのロケール設定に引きずられ、端末時刻との
突き合わせができなくなる。該当列もプレーンテキスト書式にする。

### 4. IDはクライアントで採番する（`crypto.randomUUID()`）

`product_id`・`scan_id`・`image_id`・`job_id` はブラウザ側でUUID v4を採番する。Apps Script の
往復を待たずに画像保存とジョブ記録を始められるようにするため
（[紐付け順序](product-images-and-ai-jobs.md#紐付けの順序gtinは後から決まる)が前提としている）。

---

## Products（111列）

### 商品識別（13列）

`product_id` / `gtin_jan` / `gtin_status` / `product_name` / `product_name_kana` /
`product_name_original` / `brand_name` / `manufacturer_name` / `manufacturer_address` /
`importer_name` / `manufacturer_part_number` / `country_of_origin` / `category` / `gpc_brick_code`

| 列 | 型 | 備考 |
|---|---|---|
| `product_id` | text (UUID) | **主キー。A列固定。** |
| `gtin_jan` | text | プレーンテキスト書式必須。空可（`gtin_status` で状態を示す） |
| `gtin_status` | enum | `confirmed` / `unread`（読めなかった）/ `absent`（そもそも無い） |
| `country_of_origin` | text | ISO 3166-1 alpha-2 |
| `category` | text | 例: `冷凍食品/中華惣菜` |

### 販売単位・物流階層（10列）

`packaging_level` / `is_consumer_unit` / `is_orderable_unit` / `is_despatch_unit` /
`net_content_value` / `net_content_uom` / `piece_count` / `unit_serving_weight_g` /
`units_per_case` / `parent_gtin`

boolean列（`is_*`）は `TRUE` / `FALSE` の文字列で保存する。Spreadsheetのチェックボックスは
使わない（Apps Scriptから読むと型が揺れるため）。

### 寸法・重量（13列）

`package_height_mm` / `package_width_mm` / `package_depth_mm` / `package_volume_cm3` /
`net_weight_g` / `gross_weight_g` / `drained_weight_g` / `case_height_mm` / `case_width_mm` /
`case_depth_mm` / `case_gross_weight_g` / `pallet_items_per_layer` / `pallet_layers`

**オブジェクトは展開する。** 論理モデルの `case_dimensions_mm{h,w,d}` は3列、
`pallet_configuration{items_per_layer, layers}` は2列へ。

### 物流属性（10列）

`temperature_zone` / `storage_temperature_c` / `storage_instructions` /
`transport_temperature_zone` / `shelf_life_days` / `shelf_life_after_opening` /
`refreeze_prohibited` / `stacking_limit` / `packaging_material` / `date_marking_type`

**`expiry_date` と `lot_number` はこのシートに置かない。** `SH-01-S01` の積み残し#1の決着。
両者は商品ではなく個体の属性であり、`ScanHistory` へ移した。`date_marking_type`（賞味/消費の別）は
商品の性質なので Products 側に残す。

`packaging_material` は配列 → **カンマ区切りテキスト**（`プラ,紙`）。

### 食品情報（28列）

`nutrition_basis` / `nutrition_basis_amount` / `calories_kcal` / `protein_g` / `fat_g` /
`saturated_fat_g` / `carbs_g` / `sugars_g` / `dietary_fiber_g` / `salt_equivalent_g` /
`other_nutrients` / `ingredients_text` / `additives` / `raw_material_origin` / `gmo_statement` /
`allergens_mandatory` / `allergens_recommended` / `allergen_trace_note` / `cooking_microwave_500w` /
`cooking_microwave_600w` / `cooking_microwave_1500w` / `cooking_microwave_notes` /
`cooking_pan_fry` / `cooking_oven` / `cooking_other` / `primary_cooking_method` / `cooking_notes` /
`serving_size`

| 変換 | 元 | 先 |
|---|---|---|
| オブジェクト展開 | `cooking_microwave{500w,600w,1500w,notes}` | 4列 |
| 配列→カンマ区切り | `allergens_mandatory` / `allergens_recommended` / `additives` | 各1列（`小麦,卵,大豆`） |
| 可変オブジェクト配列→JSON | `other_nutrients` | 1列にJSON文字列 |

`other_nutrients` だけJSONを許すのは、カルシウム・鉄・各種ビタミンと**商品ごとに項目名が違う**ため。
実列にすると際限なく増える。

### マーケティング情報（10列）

`image_front_url` / `image_back_url` / `marketing_message` / `usage_description` / `feature_tags` /
`usage_scene` / `package_languages` / `customer_contact` / `suggested_retail_price` / `brand_url`

`image_front_url` / `image_back_url` は**代表画像へのポインタ**。実体は `ProductImages` にあり、
ここには最新スキャンの1組を入れる。配列3列はカンマ区切り。

### サステナビリティ・認証（10列）

`recycling_marks` / `packaging_disposal_note` / `certification_marks` / `certification_numbers` /
`is_organic_jas` / `is_halal` / `is_kosher` / `dietary_suitability` / `manufacturing_certifications` /
`environmental_labels`

### メタ列（17列）

[source-confidence-revision.md](source-confidence-revision.md) で決めた保持方針の実装。

| 列 | 型 | 内容 |
|---|---|---|
| `sources_json` | text (JSON) | 項目名→source種別。値のある項目のみ |
| `confidence_json` | text (JSON) | 項目名→0.0〜1.0。値のある項目のみ |
| `confidence_overall` | number | 下記4つの**最小値** |
| `confidence_identity` | number | 商品名・GTIN群 |
| `confidence_allergens` | number | アレルゲン群（安全直結） |
| `confidence_nutrition` | number | 栄養群 |
| `confidence_cooking` | number | 調理法群 |
| `revision` | number | 初期 `1`。値が実際に変わったときだけ+1 |
| `revision_reason` | enum | `initial`/`rescan`/`ai_reanalysis`/`external_enrich`/`manual_correction`/`merge` |
| `last_job_id` | text (UUID) | この行を最後に書いた `AIJobs` の行 |
| `last_ai_model` | text | 実際に呼んだモデル文字列 |
| `last_prompt_version` | text | 例: `p2.0` |
| `record_status` | enum | `active` / `merged` / `archived` |
| `merged_into_product_id` | text (UUID) | GTIN判明で統合したときの統合先 |
| `first_scanned_at` | datetime | 最初にこの商品を撮った時刻 |
| `created_at` | datetime | 行作成 |
| `updated_at` | datetime | 最終更新（値の変更を伴わなくても更新する） |

`record_status` と `merged_into_product_id` は、`gtin_status = unread` で登録した行が後から
GTIN確定して既存行と重複したときの統合（`revision_reason = merge`）に使う。
**行は消さず `merged` にする。** 削除すると、その `product_id` を指している
`ProductImages`・`AIJobs` が迷子になる。

---

## ScanHistory（16列）

撮影1回＝1行。追記専用。

| 列 | 型 | 備考 |
|---|---|---|
| `scan_id` | text (UUID) | 主キー |
| `product_id` | text (UUID) | 解析成功後に後追いで書く。**このシート唯一の更新対象** |
| `gtin_jan` | text | 解析で得た値。プレーンテキスト書式 |
| `gtin_status` | enum | `confirmed`/`unread`/`absent` |
| `scanned_at` | datetime | シャッター時刻（表面） |
| `expiry_date` | date | **個体固有。** パッケージ印字の期限日 |
| `date_marking_type` | enum | `best_before`/`use_by`。商品側にも持つが、読めた実値をここに残す |
| `lot_number` | text | 個体固有。プレーンテキスト書式 |
| `final_status` | enum | `success`/`failed`/`aborted`。試行全体の結末 |
| `attempt_count` | number | 実行した試行回数（1〜3） |
| `best_job_id` | text (UUID) | 採用した `AIJobs` の行 |
| `duration_total_ms` | number | シャッターから結果表示までの総時間 |
| `app_version` | text | 例: `0.4.1`。回帰の切り分け用 |
| `user_agent` | text | 端末・ブラウザ判別（Android Chrome等） |
| `user_note` | text | 将来のユーザーメモ欄。MVPでは空 |
| `created_at` | datetime | |

`expiry_date` をここに置いたことで、「同じ商品（Products 1行）を3回買って3回撮った」場合に
3つの期限日が正しく別々に残る。Products側に置いていたら上書きし合っていた。

---

## ProductImages（19列）

[product-images-and-ai-jobs.md](product-images-and-ai-jobs.md) の定義をそのまま列にする。
追記専用（`product_id` のみ後追い更新）。

`image_id` / `scan_id` / `product_id` / `gtin_jan` / `face` / `drive_file_id` / `drive_url` /
`storage_path` / `captured_at` / `width_px` / `height_px` / `file_size_bytes` /
`original_size_bytes` / `mime_type` / `label_status` / `is_training_candidate` /
`exclusion_reason` / `created_at` / `updated_at`

`original_size_bytes` と `file_size_bytes` の差が `SH-03-S01｜画像圧縮・リサイズ` の効果計測
そのものになる。**圧縮率を別列で持たない**（2列から計算できる値を保存すると、片方の更新漏れで
矛盾する）。

---

## AIJobs（21列）

同じく [product-images-and-ai-jobs.md](product-images-and-ai-jobs.md) の定義をそのまま列にする。
完全追記専用。

`job_id` / `scan_id` / `product_id` / `job_type` / `attempt_no` / `input_image_ids` / `ai_model` /
`prompt_version` / `schema_version` / `status` / `started_at` / `finished_at` / `duration_ms` /
`input_tokens` / `output_tokens` / `raw_response` / `extracted_json` / `error_message` /
`validation_failures` / `created_at` / `raw_response_truncated`

| 列 | 変換 |
|---|---|
| `input_image_ids` | 配列 → カンマ区切り（通常2件） |
| `validation_failures` | 配列 → カンマ区切り |
| `raw_response` | セル上限50,000文字。超過分は切り詰め、全文は `/Scanhunt/logs/{job_id}.json` へ |
| `raw_response_truncated` | `TRUE`/`FALSE`。切り詰めた場合に立てる |

---

## シート初期化手順（`SH-02-S01` への引き継ぎ）

1. 4シートを作成し、1行目にヘッダーを書き込む。
2. ヘッダー行を固定（`setFrozenRows(1)`）。
3. プレーンテキスト書式を適用する列: `gtin_jan`・`parent_gtin`・`gpc_brick_code`・`lot_number`・
   `manufacturer_part_number`、および全日時列。
4. `Products` の `product_id` 列（A列）に重複チェックの条件付き書式を入れる（採番バグの早期発見）。
5. 各シートの1行目を保護し、誤編集を防ぐ。

**サンプルデータを初期投入しない。** テスト行が本番データに混ざると、`SH-04-S02` のGTIN重複判定が
誤作動する。

---

## 積み残し・要確認事項

1. **`Products` 111列の運用性は実データで確認する。** 横スクロールが長く、Spreadsheet上での
   目視確認は現実的でない。列グループの折りたたみと、主要20列だけを表示するフィルタビューを
   `SH-02-S01` で用意することを推奨。
2. **`ProductRevisions` シートの要否は `SH-04-S03` で判断する。** S04では4シート構成を確定させたが、
   手動修正（`SH-05-S04`）が入ると変更前の値が残らない。
3. **行数増加時の性能**。Apps Script で `getDataRange()` を毎回呼ぶと、行が数千に達した時点で
   遅くなる。GTIN検索は `TextFinder` かキャッシュ層が要る見込み。`SH-02-S03` の実装時に計測する。
4. **`confidence_*` の初期投入値**。既存プロトタイプは `confidence` を出力していないため、
   Schema更新まではすべて空になる。空と `0.0` を区別する（空＝未計測、`0.0`＝検証で否定された）。
