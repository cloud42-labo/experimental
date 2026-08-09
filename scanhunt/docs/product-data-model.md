# 商品マスター 論理データモデル（7カテゴリ・90項目）

由来: Notion `SH-01-S01｜90項目の商品マスター定義`

Scanhunt の商品マスターを **7カテゴリ・90項目** の論理データモデルとして定義する。
物理列への展開は [spreadsheet-columns.md](spreadsheet-columns.md) を参照。

## 設計サマリー

設計方針は「家庭用冷凍食品パッケージの表裏2枚から取れる情報を厚く、B2B（GS1/GPC・
サプライチェーン）拡張の受け口は薄く用意する」こと。表裏写真から直接読める食品情報を
最大カテゴリ（25項目）に据え、物流階層・寸法・パレット構成は将来のB2B入力を待つ空欄枠として
最小限に留めた（GS1 GDSN のフル属性は取り込まない）。

既存プロトタイプの8トップレベルフィールドはすべて新モデルに包含され、`nutrition`（4項目）→11項目、
`allergens`（1配列）→3項目、`cooking_instructions`（3項目）→6項目へ拡張、`brand` は `brand_name` へ
改名した。**破棄したフィールドはない。**

取得元の内訳は **AI抽出56 / AI推定13 / 手動入力13 / 外部補完5 / システム採番1 / アプリ取得2**。
必須21・任意69。AI抽出＋AI推定が69項目（77%）を占め、「表と裏の2枚を撮るだけ」で商品マスターの
大半が埋まる設計になっている。手動入力13項目はすべて寸法・物流階層系（B2B側フロー前提）で、
消費者向けUIには一切現れない。

> 取得元の4分類（AI抽出／外部補完／AI推定／手動入力）に加え、システム側が自動生成する2種を
> 例外として明示した。**システム採番**＝DBが発番する内部ID、**アプリ取得**＝アプリが撮影時に
> 保存する画像URI。どちらもAIの取得対象ではないため4分類に含めない。

---

## 商品識別

商品を一意に特定し、誰が作り誰が売るかを記録するカテゴリ。GTIN/JANが主キー候補だが、
輸入食材ではJANが無い・読めないケースがあるため内部IDを別に持つ。

| 項目名（日本語） | field_name | 型 | 必須 | 取得元 | 説明・例 |
|---|---|---|---|---|---|
| 商品ID | `product_id` | string (UUID) | 必須 | システム採番 | 内部主キー。JAN不明・重複時も一意性を担保する |
| GTIN／JANコード | `gtin_jan` | string (8/13/14桁) | 必須 | AI抽出 | 裏面バーコードから読取。例: `4900000000000` |
| 商品名 | `product_name` | string | 必須 | AI抽出 | 表面の商品名。例: `もっちり水餃子` |
| 商品名（かな） | `product_name_kana` | string | 任意 | AI推定 | 検索・並び替え用。例: `もっちりすいぎょうざ` |
| 原語商品名 | `product_name_original` | string | 任意 | AI抽出 | 輸入品の原語表記。例: `Gyoza aux légumes` |
| ブランド名 | `brand_name` | string | 必須 | AI抽出 | 表面のブランド／メーカー名。例: `Picard` |
| 製造者・販売者名 | `manufacturer_name` | string | 任意 | AI抽出 | 裏面「製造者」「販売者」欄 |
| 製造所所在地 | `manufacturer_address` | string | 任意 | AI抽出 | 裏面表示欄。製造所固有記号を含む場合あり |
| 輸入者名 | `importer_name` | string | 任意 | AI抽出 | 輸入食材の日本語シールに記載 |
| メーカー品番 | `manufacturer_part_number` | string | 任意 | 外部補完 | 型番・自社コード。GTINマスターから引く |
| 原産国 | `country_of_origin` | string (ISO 3166-1 alpha-2) | 任意 | AI抽出 | 例: `FR`、`JP`。表記ゆれはコードへ正規化 |
| 商品カテゴリ | `category` | enum | 必須 | AI推定 | 自社分類。例: `冷凍食品/中華惣菜`、`輸入食材/デリ` |
| GPCブリックコード | `gpc_brick_code` | string (8桁) | 任意 | 外部補完 | GS1 GPC。B2B連携時に付与。例: `10000159` |

---

## 販売単位・物流階層

「消費者が買う1袋」と「ケース」を区別する層。Scanhunt が扱うのは基本すべて消費者単位（each）だが、
B2B提供時に上位階層へ紐付けられるよう最小限の枠を持つ。

| 項目名（日本語） | field_name | 型 | 必須 | 取得元 | 説明・例 |
|---|---|---|---|---|---|
| 荷姿階層区分 | `packaging_level` | enum (`each`/`pack`/`case`/`pallet`) | 必須 | AI推定 | 消費者撮影の場合はほぼ `each` 固定 |
| 消費者購入単位フラグ | `is_consumer_unit` | boolean | 必須 | AI推定 | 栄養成分表示があれば `true` と判定できる |
| 発注単位フラグ | `is_orderable_unit` | boolean | 任意 | 手動入力 | B2B発注可能単位か。GS1準拠 |
| 出荷単位フラグ | `is_despatch_unit` | boolean | 任意 | 手動入力 | 単体で出荷される単位か |
| 内容量（数値） | `net_content_value` | number | 必須 | AI抽出 | 例: `300` |
| 内容量単位 | `net_content_uom` | enum (`g`/`kg`/`ml`/`L`/`個`/`枚`/`食`) | 必須 | AI抽出 | 例: `g` |
| 内容個数 | `piece_count` | number | 任意 | AI抽出 | 「12個入」など。例: `12` |
| 1個あたり重量 | `unit_serving_weight_g` | number | 任意 | AI推定 | `net_content_value ÷ piece_count` |
| ケース入数 | `units_per_case` | number | 任意 | 手動入力 | ケース内の消費者単位数。例: `20` |
| 上位階層GTIN | `parent_gtin` | string (14桁) | 任意 | 手動入力 | 所属するケースのITF-14 |

---

## 寸法・重量

冷凍サプライチェーンの容積計算（保冷ボックス何個入るか）を支えるカテゴリ。
**消費者撮影では原理的に取得できない**ため、3辺と容積を除きほぼ手動入力枠。
将来の実測・メーカー提供を待つ。

| 項目名（日本語） | field_name | 型 | 必須 | 取得元 | 説明・例 |
|---|---|---|---|---|---|
| 包装高さ | `package_height_mm` | number | 任意 | 手動入力 | 単位mm。例: `220` |
| 包装幅 | `package_width_mm` | number | 任意 | 手動入力 | 単位mm。例: `160` |
| 包装奥行 | `package_depth_mm` | number | 任意 | 手動入力 | 単位mm。例: `45` |
| 包装容積 | `package_volume_cm3` | number | 任意 | AI推定 | 3辺から算出。矩形近似である旨をメタで持つ |
| 正味重量 | `net_weight_g` | number | 必須 | AI抽出 | 内容量表示から。例: `300` |
| 総重量（包装込み） | `gross_weight_g` | number | 任意 | 手動入力 | 実測前提 |
| 固形量 | `drained_weight_g` | number | 任意 | AI抽出 | 表示がある商品のみ。例: `180` |
| ケース外寸 | `case_dimensions_mm` | object `{h,w,d}` | 任意 | 手動入力 | B2B専用 |
| ケース総重量 | `case_gross_weight_g` | number | 任意 | 手動入力 | B2B専用 |
| パレット積付構成 | `pallet_configuration` | object `{items_per_layer, layers}` | 任意 | 手動入力 | B2B専用。例: `{12, 8}` |

---

## 物流属性

温度帯と日付管理。冷凍食品カテゴリの中核であり、B2B価値が最も高い領域。
`temperature_zone` は必須。

| 項目名（日本語） | field_name | 型 | 必須 | 取得元 | 説明・例 |
|---|---|---|---|---|---|
| 温度帯 | `temperature_zone` | enum (`frozen`/`chilled`/`ambient`) | 必須 | AI抽出 | 「要冷凍」表示から判定。例: `frozen` |
| 推奨保存温度 | `storage_temperature_c` | number | 任意 | AI抽出 | 例: `-18`（「-18℃以下で保存」） |
| 保存方法テキスト | `storage_instructions` | string | 任意 | AI抽出 | 原文保持。例: `-18℃以下で保存してください` |
| 輸送温度帯 | `transport_temperature_zone` | enum | 任意 | AI推定 | 通常は `temperature_zone` と同値 |
| 期限表示区分 | `date_marking_type` | enum (`best_before`/`use_by`) | 任意 | AI抽出 | 賞味期限／消費期限の別 |
| 期限日 | `expiry_date` | date (ISO 8601) | 任意 | AI抽出 | **個体固有。** 物理配置は `ScanHistory`（S04で確定） |
| 賞味期間（日数） | `shelf_life_days` | number | 任意 | 外部補完 | 製造日からの日数。マスターから引く |
| 開封後保存目安 | `shelf_life_after_opening` | string | 任意 | AI抽出 | 例: `開封後はお早めにお召し上がりください` |
| ロット／製造番号 | `lot_number` | string | 任意 | AI抽出 | **個体固有。** トレーサビリティ用 |
| 再凍結禁止表示 | `refreeze_prohibited` | boolean | 任意 | AI抽出 | 「一度解凍したものを再び凍らせない」表示 |
| 積み重ね上限 | `stacking_limit` | number | 任意 | 手動入力 | 段数上限。B2B専用 |
| 包装材質 | `packaging_material` | array\<enum\> | 任意 | AI抽出 | 例: `["プラ", "紙"]` |

---

## 食品情報

最大カテゴリ（25項目）。**アプリのユーザー価値がここに集中する**（調理法・アレルゲン・栄養）。
表示単位の取り違えが致命的なので、`nutrition_basis` を必須にして「100gあたり」か「1袋あたり」かを
常に明示する。

| 項目名（日本語） | field_name | 型 | 必須 | 取得元 | 説明・例 |
|---|---|---|---|---|---|
| 栄養成分表示基準 | `nutrition_basis` | enum (`per_100g`/`per_100ml`/`per_serving`/`per_package`) | 必須 | AI抽出 | **必須。** 取り違えると全数値が無意味になる |
| 表示基準量 | `nutrition_basis_amount` | number | 任意 | AI抽出 | 例: `100`（`per_serving` 時は1食分のg数） |
| 熱量 | `calories_kcal` | number | 必須 | AI抽出 | 例: `350` |
| たんぱく質 | `protein_g` | number | 必須 | AI抽出 | 例: `12.5` |
| 脂質 | `fat_g` | number | 必須 | AI抽出 | 例: `15.0` |
| 飽和脂肪酸 | `saturated_fat_g` | number | 任意 | AI抽出 | 任意表示項目 |
| 炭水化物 | `carbs_g` | number | 必須 | AI抽出 | 例: `40.0` |
| 糖質 | `sugars_g` | number | 任意 | AI抽出 | 炭水化物を糖質／食物繊維に分割表示する商品のみ |
| 食物繊維 | `dietary_fiber_g` | number | 任意 | AI抽出 | 同上 |
| 食塩相当量 | `salt_equivalent_g` | number | 必須 | AI抽出 | 日本の義務表示5項目の1つ。例: `1.8` |
| その他栄養素 | `other_nutrients` | array\<object \{name, value, unit\}\> | 任意 | AI抽出 | カルシウム・鉄・ビタミン等の可変枠 |
| 原材料名（原文） | `ingredients_text` | string | 必須 | AI抽出 | 裏面原文をそのまま保持。分解はアプリ側で行う |
| 添加物 | `additives` | array\<string\> | 任意 | AI抽出 | 例: `["調味料(アミノ酸等)", "増粘剤"]` |
| 原料原産地 | `raw_material_origin` | string | 任意 | AI抽出 | 例: `豚肉（アメリカ産）` |
| 遺伝子組換え表示 | `gmo_statement` | string | 任意 | AI抽出 | 例: `大豆（遺伝子組換えでない）` |
| 特定原材料（義務8品目） | `allergens_mandatory` | array\<enum\> | 必須 | AI抽出 | えび/かに/くるみ/小麦/そば/卵/乳/落花生。空配列も有効値 |
| 推奨表示アレルゲン（20品目） | `allergens_recommended` | array\<enum\> | 任意 | AI抽出 | 大豆/牛肉/ごま/カシューナッツ等 |
| コンタミ注意書き | `allergen_trace_note` | string | 任意 | AI抽出 | 例: `本製品はえびを含む製品と同じ設備で製造しています` |
| 調理法（電子レンジ） | `cooking_microwave` | object `{wattage_500w, wattage_600w, wattage_1500w, notes}` | 任意 | AI抽出 | 例: `{"wattage_600w": "3分"}` |
| 調理法（フライパン） | `cooking_pan_fry` | string | 任意 | AI抽出 | 例: `水50mlを入れフタをして5分` |
| 調理法（オーブン／トースター） | `cooking_oven` | string | 任意 | AI抽出 | 例: `1000Wで7分` |
| 調理法（その他） | `cooking_other` | string | 任意 | AI抽出 | 湯煎・自然解凍・揚げる等 |
| 主調理法 | `primary_cooking_method` | enum (`microwave`/`pan_fry`/`oven`/`boil`/`deep_fry`/`thaw`) | 任意 | AI推定 | **結果画面のラベル切替に使う**（`BUG-SH-02` の根拠フィールド） |
| 調理上の注意 | `cooking_notes` | string | 任意 | AI抽出 | 例: `加熱後は熱いのでご注意ください` |
| 1食分の目安 | `serving_size` | string | 任意 | AI抽出 | 例: `1袋(300g)`、`5個(120g)` |

---

## マーケティング情報

パッケージ表面の訴求と、アプリが撮影した画像。画像は物理的には `ProductImages` へ分離し、
ここではURI参照のみを持つ（[product-images-and-ai-jobs.md](product-images-and-ai-jobs.md)）。

| 項目名（日本語） | field_name | 型 | 必須 | 取得元 | 説明・例 |
|---|---|---|---|---|---|
| 表面画像 | `image_front_url` | string (URL) | 必須 | アプリ取得 | 撮影した表面写真の保存先。Drive/GCS URI |
| 裏面画像 | `image_back_url` | string (URL) | 必須 | アプリ取得 | 撮影した裏面写真の保存先 |
| キャッチコピー | `marketing_message` | string | 任意 | AI抽出 | 表面訴求文。例: `もっちり皮で包んだ本格水餃子` |
| 用途・食シーン説明 | `usage_description` | string | 任意 | AI抽出 | 例: `お弁当のおかずに、おつまみに` |
| 商品特徴タグ | `feature_tags` | array\<string\> | 任意 | AI推定 | 例: `["時短", "レンジのみ", "大容量"]` |
| 対象シーン | `usage_scene` | array\<enum\> | 任意 | AI推定 | 例: `["弁当", "夕食", "おつまみ"]` |
| パッケージ表記言語 | `package_languages` | array\<enum\> | 任意 | AI推定 | 輸入品判定に使う。例: `["ja", "fr"]` |
| お客様相談窓口 | `customer_contact` | string | 任意 | AI抽出 | 裏面の電話番号・問合せ先 |
| 希望小売価格 | `suggested_retail_price` | number | 任意 | 外部補完 | パッケージに価格表示がないため外部依存 |
| ブランドサイトURL | `brand_url` | string (URL) | 任意 | 外部補完 | 公式商品ページ |

---

## サステナビリティ・認証

パッケージ上の認証マーク・リサイクルマークの読取が中心。輸入食材ではハラール／コーシャ／
有機認証が実際に印字されており、ターゲット層別フロントエンド（ヴィーガンスキャナー等）の
判定材料になる。

| 項目名（日本語） | field_name | 型 | 必須 | 取得元 | 説明・例 |
|---|---|---|---|---|---|
| 容器包装識別マーク | `recycling_marks` | array\<enum\> | 任意 | AI抽出 | 例: `["プラ", "紙", "アルミ"]` |
| 分別排出の注意書き | `packaging_disposal_note` | string | 任意 | AI抽出 | 例: `お住まいの地域の区分に従って捨ててください` |
| 認証マーク | `certification_marks` | array\<enum\> | 任意 | AI抽出 | 有機JAS/MSC/ASC/FSC/RSPO/レインフォレスト等 |
| 認証番号 | `certification_numbers` | array\<string\> | 任意 | AI抽出 | 認証機関の登録番号 |
| 有機JAS適合 | `is_organic_jas` | boolean | 任意 | AI推定 | `certification_marks` から導出 |
| ハラール認証 | `is_halal` | boolean | 任意 | AI抽出 | 輸入食材で頻出 |
| コーシャ認証 | `is_kosher` | boolean | 任意 | AI抽出 | 輸入食材で頻出 |
| 食事適合区分 | `dietary_suitability` | array\<enum\> | 任意 | AI推定 | `vegan`/`vegetarian`/`gluten_free`。原材料から推定 |
| 製造工程認証 | `manufacturing_certifications` | array\<string\> | 任意 | 手動入力 | HACCP/ISO 22000/FSSC 22000等。パッケージ非記載が多い |
| 環境ラベル | `environmental_labels` | array\<string\> | 任意 | AI抽出 | カーボンフットプリント表示等 |

---

## 既存プロトタイプJSONとの対応表

| 既存フィールド | 新モデルでの対応 | 変化 |
|---|---|---|
| `gtin_jan` | `gtin_jan`（商品識別） | そのまま。`gpc_brick_code`・`manufacturer_part_number` を外部補完枠として追加 |
| `product_name` | `product_name`（商品識別） | そのまま。`product_name_kana`・`product_name_original` を追加 |
| `brand` | `brand_name`（商品識別） | **改名**。`manufacturer_name`／`importer_name`／`manufacturer_address` へ分化 |
| `category` | `category`（商品識別） | そのまま。enum化し、`feature_tags`・`usage_scene` をマーケ側へ分離 |
| `temperature_zone` | `temperature_zone`（物流属性） | そのまま。`storage_temperature_c` ほか物流属性11項目を新設 |
| `cooking_instructions`（`microwave`/`pan_fry`/`other_notes`） | `cooking_microwave`／`cooking_pan_fry`／`cooking_notes` ＋新設 `cooking_oven`／`cooking_other`／`primary_cooking_method` | **フラット化＋3項目追加**。`primary_cooking_method` が結果画面のラベル切替を担う |
| `nutrition`（4項目） | `calories_kcal`／`protein_g`／`fat_g`／`carbs_g` ＋7項目 | **フラット化＋拡張**（食塩相当量・糖質・食物繊維・飽和脂肪酸・その他栄養素・表示基準2項目）。`nutrition_basis` 必須化が最大の変更 |
| `allergens`（単一配列） | `allergens_mandatory`／`allergens_recommended`／`allergen_trace_note` | **3分割**。義務8品目と推奨20品目を混在させない |

破棄したフィールドはなし。既存プロトタイプの抽出JSONは、新モデルの部分集合としてそのまま移行できる。

---

## 積み残し・要確認事項

S01 時点の積み残し6件。うち#1・#2・#4は後続Storyで決着済み（下記に決着先を記載）。

1. **個体固有フィールドの置き場所** — `expiry_date` と `lot_number` は商品マスター（GTIN単位）
   ではなく撮影1件ごとの属性。**→ `SH-01-S04` で `ScanHistory` へ置くと決着**
   （[spreadsheet-columns.md](spreadsheet-columns.md)）。
2. **AI抽出値の信頼度メタデータ** — 全90項目に `confidence`・`source` を付けると列数が倍増する。
   **→ `SH-01-S03` でJSON列2本＋昇格列5本と決着**
   （[source-confidence-revision.md](source-confidence-revision.md)）。
3. **手動入力13項目の入力主体** — 寸法・パレット構成をB2Bフローで誰がいつ入れるのか
   （メーカー提供／実測代行／推定値許容）が未定。`EPIC-SH-07` の設計時に確定させる。**未決着。**
4. **`nutrition_basis` が読めなかった場合の扱い** — **→ `SH-01-S03` で決着。
   `per_100g` のデフォルト仮定はしない。**
5. **アレルゲンenumの版管理** — くるみの義務化のように特定原材料8品目は法改正で変わる。
   enum定義をコードに直書きせず、マスターとして外出しする前提。**未決着。**
6. **外部補完5項目のデータソース未定** — GTIN/JANマスター（GS1 Japan、商用DB等）の選定・費用が
   未検討。`EPIC-SH-05` の着手前に確認が必要。**未決着。**
