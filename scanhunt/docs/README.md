# Scanhunt 設計仕様

Scanhunt のデータモデルと保存設計の**正本**。実装（`scanhunt/index.html`、および将来の
Apps Script）はここを参照する。

## 正本の分担

| 情報 | 正本 | Notionでの扱い |
|---|---|---|
| データモデル・列定義・保存ルール（この配下） | **GitHub** | 要約とリンクのみ |
| Prompt本文・JSON Schema本体 | **GitHub**（`scanhunt/index.html`） | 複製しない |
| Epic・Story・受入条件・進捗 | **Notion** | 正本 |
| 意思決定・人間依頼 | **Notion** | 正本 |

設計の議論と受入条件は Notion の
[Vibe Product Development](https://app.notion.com/p/3affbd826f3b819d84ebe3015c6f946b)
にあり、確定した仕様の本体はこのディレクトリにある。**Notion本文と食い違った場合は
このディレクトリを正とする。** 仕様を変えるときはここを更新し、Notionのタスクからリンクする。

## 文書一覧

| 文書 | 内容 | 由来Story |
|---|---|---|
| [product-data-model.md](product-data-model.md) | 商品マスターの論理データモデル（7カテゴリ・90項目） | `SH-01-S01` |
| [product-images-and-ai-jobs.md](product-images-and-ai-jobs.md) | 画像証跡（ProductImages）とAI解析履歴（AIJobs）、Drive保存パスルール | `SH-01-S02` |
| [source-confidence-revision.md](source-confidence-revision.md) | 取得元（source）・信頼度（confidence）・リビジョン管理 | `SH-01-S03` |
| [spreadsheet-columns.md](spreadsheet-columns.md) | Google Spreadsheet 4シートの実列定義（計167列）と実装上の必須ルール | `SH-01-S04` |

読む順序は上から。`product-data-model.md` が論理モデル、`spreadsheet-columns.md` が
それを物理表へ落としたもの。実装するときは後者を見る。

## 主要な設計判断（要約）

- **栄養値は `nutrition_basis` とセットでなければ意味を持たない。** 表示基準が読めない場合、
  `per_100g` をデフォルト仮定しない。値は保存するが信頼度を頭打ちにし、UIでは基準不明を明示する。
- **AIJobs は「解析1件」ではなく「試行1回」を1行にする。** 失敗試行を残さないと成功率が
  計算できず、モデル比較（`SH-06-S04`）が成立しない。
- **confidence はAIの自己申告ではなく、検証で裏が取れた度合い。** チェックディジット・
  内部整合・リトライ間一致など、外形的に検証できる根拠から算出する。
- **`manual` は常に他の取得元を上書きする。** 人が直した値をAIの再解析が書き戻してはならない。
- **個体固有の値（`expiry_date` / `lot_number`）は Products ではなく ScanHistory に置く。**
  同じ商品を複数回撮ったときに上書きし合わないため。
