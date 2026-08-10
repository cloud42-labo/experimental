# 取得元・Confidence・バージョン管理

由来: Notion `SH-01-S03｜取得元・Confidence・バージョン管理設計`

## 設計サマリー

`SH-01-S01` で積み残した「全90項目に `confidence` と `source` を付けると列数が倍増する」問題に
決着をつけた。答えは **JSON列2本＋昇格列**。

- 全項目分の `source`・`confidence` は `Products` の `sources_json`・`confidence_json` という
  **各1列のJSON** に格納する。列は増えない。
- そのうち**運用で絞り込み・並べ替えに使う数項目だけ**を独立した列へ「昇格」させる。
  Spreadsheetはセル内JSONで絞り込めないため、フィルタしたいものだけ実列にする。

もう1つの決定は `confidence` の意味づけ。**`confidence` はAIの自己申告ではなく、検証で裏が
取れた度合いとする。** LLMの自己申告スコアは較正されておらず、Go/No-Go検証で観測した
「自信ありげに無関係な内容を生成する」失敗を弾けない。チェックディジット・内部整合・
リトライ間一致といった**外形的に検証できる根拠**から算出する。

---

## source種別

`SH-01-S01` で定義した取得元区分を、そのまま値として保持する形に落とした。`computed` のみ新設
（S01では「AI推定」に含めていたが、算術で決まる値はAIの推定と区別する）。

| 値 | 意味 | 例 |
|---|---|---|
| `ai_extracted` | 画像に書かれている内容をAIが読み取った | `product_name`、`allergens_mandatory` |
| `ai_inferred` | 画像に書かれていないがAIが推定した | `category`、`dietary_suitability` |
| `computed` | 他の項目から算術で決まる | `unit_serving_weight_g`、`package_volume_cm3` |
| `external_master` | GTIN等をキーに外部データソースから引いた | `gpc_brick_code`、`shelf_life_days` |
| `manual` | 人が入力・修正した | 寸法・パレット構成、AI誤りの訂正 |
| `system` | システムが採番・記録した | `product_id`、`created_at` |
| `app` | アプリが撮影時に記録した | `image_front_url`、`captured_at` |

### `manual` は常に他を上書きする

同じ項目に複数の取得元が競合した場合の優先順位を固定する。

```
manual > external_master > ai_extracted > ai_inferred > computed
```

**人が直した値をAIの再解析が上書きしてはならない。** 再解析（`SH-06-S03`）はモデル更新のたびに
全項目を書き直す性質があるため、この規則が無いと訂正が消える。`source = manual` の項目は
再解析の書き込み対象から除外する。

---

## confidenceの粒度

### 決定: JSON列に全項目分＋5列の昇格

| 持ち方 | 採否 | 理由 |
|---|---|---|
| 全90項目に専用列 | ✕ | 列数が180超。Spreadsheetの可読性・Apps Scriptの処理量が破綻する |
| レコード単位で1つ | ✕ | 「アレルゲンは怪しいが商品名は確実」を表現できず、行動に繋がらない |
| **JSON列＋昇格列** | ✓ | 列を増やさず項目単位の粒度を保ち、絞り込みが要るものだけ実列にする |

### JSON列の形

`Products` に2列だけ追加する。

```json
// sources_json
{"gtin_jan":"ai_extracted","category":"ai_inferred","package_height_mm":"manual"}

// confidence_json
{"gtin_jan":1.0,"product_name":0.9,"allergens_mandatory":0.6,"nutrition_basis":0.3}
```

**値が入っていない項目はキーごと省く。** 90項目すべてのキーを常に書くとセルが膨らむ。
キーが無い＝未取得と解釈する。

### 昇格列（実列にするもの）

| 列 | 型 | 昇格させる理由 |
|---|---|---|
| `confidence_overall` | number (0.0–1.0) | 一覧で品質の低い商品から潰すため |
| `confidence_identity` | number | 商品名・GTINが怪しい行＝重複や誤登録の温床 |
| `confidence_allergens` | number | **安全に直結する。** 低信頼のものを機械的に洗い出せる必要がある |
| `confidence_nutrition` | number | 数値の誤りが最も気付かれにくい |
| `confidence_cooking` | number | アプリの主用途。低いものはPrompt改善の対象 |

`confidence_overall` は上記4グループの**最小値**とする。平均ではない。
**アレルゲンだけが0.2でも「全体としては良好」と表示してはいけない。**

---

## confidenceの算出根拠

自己申告ではなく検証由来とする、という方針の具体化。0.0〜1.0で保持し、下記の判定を積む。

| 検証 | 対象 | 効果 |
|---|---|---|
| JANチェックディジット | `gtin_jan` | 合格→`1.0`、不合格→`0.0`（決定的に判定できる唯一の項目） |
| 主要フィールドの存在 | 既存実装の検証ロジック | 欠落→該当グループを `0.3` 以下へ |
| 栄養の内部整合 | `calories_kcal` vs P4/F9/C4の概算 | 乖離20%超→`nutrition` を減点 |
| 表示基準の取得可否 | `nutrition_basis` | **取得できない場合、`nutrition` グループ全体を `0.3` で頭打ちにする** |
| リトライ間の一致 | 2回以上成功した場合の値の一致 | 一致→加点、不一致→両方を減点 |
| 人による確認 | `label_status = human_verified` | 該当項目を `1.0` に固定 |

### `nutrition_basis` が読めなかった場合（`SH-01-S01` 積み残し#4の決着）

**`per_100g` をデフォルト仮定しない。** 1袋あたり表示の商品を100gあたりと誤認すると、
実際の3倍のカロリーを表示するような誤りが静かに残る。

- `nutrition_basis` が取れない場合、`nutrition` グループの各項目は保存する（捨てない）が、
  `confidence_nutrition` を `0.3` で頭打ちにする。
- アプリのUIでは**基準が不明である旨を明示**し、数値を単独で見せない。
  （実装済み: `scanhunt/index.html` の `nutritionSummary()`。基準不明時は「基準不明」を表示する）
- 再解析（`SH-06-S03`）の優先対象にする。

---

## revision番号の運用

`Products` に `revision`（number、初期値 `1`）と `revision_reason` を持つ。

### 上げる条件・上げない条件

- **いずれかの項目の値が実際に変わったときだけ+1する。** 同じ値で再確認しただけでは上げない。
  再解析を回すたびに番号が進むと、`revision` が「変更回数」ではなく「解析回数」になり意味を失う。
- `confidence` だけが変わった場合は上げない（値が同じなら商品情報としては同一）。
- 値の変更を伴わない `updated_at` の更新は許容する。

| `revision_reason` | 発生源 |
|---|---|
| `initial` | 新規登録（`revision = 1`） |
| `rescan` | 同一GTINを再撮影して値が変わった |
| `ai_reanalysis` | モデル更新後の再解析で値が変わった |
| `external_enrich` | 外部マスターから項目が補完された |
| `manual_correction` | 人が訂正した |
| `merge` | GTIN不明で登録した行と、後から判明した行を統合した |

### 更新履歴の置き場は `SH-04-S03` で確定する

`Products` は**最新スナップショット1行**とし、履歴行は持たない。AI由来の変更は
`AIJobs.extracted_json` を時系列に並べれば復元できるため、MVPではこれで足りる。

ただし**手動修正（`SH-05-S04`）が入ると、変更前の値がどこにも残らない**。
`ProductRevisions`（追記専用）の追加が必要になる見込みだが、`SH-01-S04` の受入条件に記載の
シートは4つであり、S03では5つ目を確定させない。`SH-04-S03｜商品更新・リビジョン管理` の
受入条件「リビジョン番号と更新履歴が残る」を満たす方法として、そこで判断する。

---

## AIモデル / Prompt Version の保持方法

### どこに持つか

| 場所 | 持つもの | 理由 |
|---|---|---|
| `AIJobs` | `ai_model`・`prompt_version`・`schema_version`（試行ごと） | 実行の事実。`SH-06-S04` のモデル比較の元データ |
| `Products` | `last_job_id`・`last_ai_model`・`last_prompt_version` | 「この商品情報を最後に書いたのは何か」を1行で辿るため |
| GitHub | **Prompt本文・JSON Schema本体** | 正本。Notionへ本文を複製しない |

`ai_model` は**エイリアスではなく実際に呼んだ文字列**を残す。`gemini-flash-latest` のような
エイリアスは指す実体が時期によって変わるため、後から「いつのモデルか」を復元できなくなる
（[brain: notes/gemini-model-deprecation-quirks](https://github.com/cloud42-labo/brain/blob/main/notes/gemini-model-deprecation-quirks.md)
で踏んだ問題と同根）。エイリアスで呼んだ場合は、応答から実モデル名が取れればそれも併記する。

### 採番規則

| 種別 | 形式 | 上げるとき |
|---|---|---|
| `prompt_version` | `p{major}.{minor}` 例: `p2.0` | major＝抽出項目セットの変更、minor＝文言・指示の調整 |
| `schema_version` | `s{n}` 例: `s2` | `responseSchema` の構造が変わったとき |

**PromptとSchemaは独立に版を持つ。** 同じSchemaのままPromptだけ改善する場面が多く、
まとめると比較の粒度が落ちる。`SH-03-S03｜Gemini出力JSON最適化` で両方が上がるため、
その実装時に `p2.0` / `s2` を初版として付ける（実装済み）。

---

## 積み残し・要確認事項

1. **リトライ間一致の判定コスト**。2回目以降の成功結果と1回目を突き合わせるには、失敗しても
   解析を続ける（＝1回成功したら止めない）必要があり、API消費が増える。MVPでは
   「最初の成功で確定、一致判定は行わない」とし、`confidence` の加点要素としては将来
   有効化する扱いを推奨。
2. **`confidence_overall` を最小値にすると、ほぼ全商品が低スコアになる可能性**。
   アレルゲン表示のない商品（空配列が正解）を低信頼と誤判定しないよう、「該当なしが正解」と
   「読めなかった」の区別が要る。`allergens_mandatory` が空配列のとき、コンタミ注意書きの
   有無などから判断できるかは実データで確認する。
3. **手動優先の例外**。人が誤って入力した値をAIが正しく読んでいる場合、現規則ではAIの正解が
   反映されない。訂正の訂正をどう扱うかは `SH-05-S04｜手動修正UI` で検討する。
4. **`sources_json`／`confidence_json` のサイズ**。90項目すべてが埋まると1セルあたり2〜3KB程度。
   Spreadsheetのセル上限（50,000文字）には余裕があるが、行数が増えたときのApps Scriptの
   パース時間は `SH-02-S03` で計測する。
