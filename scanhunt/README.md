# Scanhunt（仮）

冷凍食品・輸入食材の「前面（表）」と「後面（裏）」を撮るだけで、電子レンジの調理手順・
栄養成分・アレルギー物質・JANコードをAIが読み取り、外箱を捨てても困らない「マイ・レシピ帳」
として保存するスキャンアプリの試作。

## コンセプト

- 課題: 冷凍食品・輸入食材は外箱を捨てると加熱時間や解凍方法が分からなくなる。輸入品は
  裏面の日本語成分シールが極小で読みづらい
- 解決: 表と裏の2枚をスキャンするだけで、調理法・栄養成分・アレルギー情報を構造化して保存
- 裏側の狙い: フロントエンドはターゲット層ごとに複数展開しつつ、裏側のAIエンジン・
  商品マスターデータベースは1つに共通化する。将来的にサプライチェーン（温度帯・容積など）
  向けのB2Bデータとして小売業に提供することを見据える

## 現状

`index.html` は Google AI Studio (Gemini) で vibe coding したUIプロトタイプ。カメラで
表→裏を連続撮影するフロー（触覚フィードバック、3Dフリップ演出、ゼロウェイティングの
自動シャッター）に加え、表裏それぞれのシャッター時に実フレームをcanvasでキャプチャし、
Gemini API（`gemini-flash-latest`、マルチモーダル、`responseSchema`で下記JSON構造を指定）へ
クライアントサイドから直接送る実装まで済んでいる。APIキーは初回のみ`prompt()`で入力し、
ブラウザの`localStorage`にのみ保存（ソース・Notionには書かない）。キー未設定時や抽出失敗時は
モックデータにフォールバックする。

実写真3点（国内2点・輸入1点=Picard仏製品の日本語シール）でのGo/No-Go検証を実施し、
**Conditional Go**と判定した。輸入品の極小日本語シールも含め成功時は非常に高精度だが、
3回に1回程度の頻度で出力が不安定になる（無関係な内容の生成・タイムアウト・主要フィールド
欠落）ことを確認したため、最大3回までの自動リトライ＋出力検証（JSONパース成功かつ
cooking_instructions/nutrition/allergensのいずれかが埋まっていること）を実装済み。
詳細はNotion「Roadmap & Epics」の `Scanhunt: Gemini API抽出精度検証` Epic（STORY-05・06）を参照。

- [x] Gemini API連携（表裏2枚の画像 → JSON構造化データ抽出）
- [x] 実際のパッケージ写真での抽出精度検証（Go/No-Go判定）— Conditional Go
- [x] 抽出のリトライ・出力検証（不安定な出力への対策）
- [x] 画像圧縮・リサイズ（長辺1280px / JPEG品質75%）
- [x] 解析中の進捗表示と、撮り直さずに再解析できる失敗時導線
- [x] 90項目モデルへ対応したフラットJSON（`p2.0` / `s2`）
- [x] 調理方式（電子レンジ・オーブン・フライパン・油調理・ゆで・自然解凍）別の表示切替
- [ ] 抽出結果の永続化（マイ・レシピ帳のデータ保存）
- [ ] JANコード重複時のフィードバックUI

## 設計仕様

データモデル・列定義・保存ルールの**正本は [docs/](docs/) 配下**にある。Notionには要約と
リンクだけを置く（Notionは計画・判断・進捗の正本、GitHubはコード・仕様・履歴の正本）。

| 文書 | 内容 |
|---|---|
| [docs/product-data-model.md](docs/product-data-model.md) | 商品マスターの論理データモデル（7カテゴリ・90項目） |
| [docs/product-images-and-ai-jobs.md](docs/product-images-and-ai-jobs.md) | 画像証跡とAI解析履歴、Drive保存パスルール |
| [docs/source-confidence-revision.md](docs/source-confidence-revision.md) | 取得元・信頼度・リビジョン管理 |
| [docs/spreadsheet-columns.md](docs/spreadsheet-columns.md) | Spreadsheet 4シートの実列定義（計168列）と実装上の必須ルール |

### 旧プロトタイプのJSON構造（参考）

下記は Go/No-Go 検証時点の抽出JSON。**現行の正は上記の90項目モデル**で、こちらはその部分集合。
ネストしていた `cooking_instructions` / `nutrition` は Spreadsheet の列名と1対1で対応する
フラット構造へ置き換わっている（`cooking_instructions.microwave.wattage_500w` 等の旧ネスト構造は
`v0.4.0` で廃止した）。

```json
{
  "gtin_jan": "4900000000000",
  "product_name": "商品名",
  "brand_name": "ブランド/メーカー名",
  "category": "冷凍食品",
  "temperature_zone": "frozen",
  "nutrition_basis": "per_100g",
  "calories_kcal": 350, "protein_g": 12.5, "fat_g": 15.0, "carbs_g": 40.0, "salt_equivalent_g": 1.8,
  "allergens_mandatory": ["小麦", "卵"],
  "allergens_recommended": ["大豆"],
  "primary_cooking_method": "microwave",
  "cooking_microwave_500w": "3分30秒",
  "cooking_microwave_600w": "3分",
  "cooking_pan_fry": "水50mlを入れてフタをし5分",
  "cooking_notes": "調理上の注意点"
}
```

抽出の規則（プロンプトで指示している）。

- **読み取れない項目はキーごと省略する。** `null`・空文字・「不明」を入れない。
- 栄養成分は `nutrition_basis`（100gあたり／1食あたり等）とセットで返す。基準が読めない場合は
  栄養成分自体を省略する。基準を取り違えると全数値が無意味になるため。
- `allergens_mandatory` は特定原材料8品目のみ。推奨表示20品目は `allergens_recommended` へ分ける。
- `category` 以外は推測しない（パッケージに印字されている内容だけを抽出する）。

Prompt と JSON Schema は独立に版を持つ（現在 `p2.0` / `s2`）。

## 動作確認

調理方式の判定（`pickCookMethod`）には回帰ケースを同梱している。
`index.html?selftest=1` で開くと、8ケースの判定結果が画面に出る。先頭のケースは
PR #71 の実機確認で見つかった「フライパン調理なのに MICROWAVE / 500W と表示される」取り違え。

同じクエリパラメータのとき `window.scanhuntTest` に内部関数を公開するため、カメラや
APIキーが無くても結果画面・解析中画面を実機のブラウザで確認できる。

## 技術スタック（今後の実装方針）

- フロントエンド: React / Next.js (TypeScript) + Tailwind CSS + Lucide Icons
- カメラスキャン: HTML5 WebRTC (react-webcam 等)
- AI OCR/解析: Gemini API（マルチモーダル）

詳しい検討の経緯（カテゴリ選定・UXフロー設計・vibe codingの進め方）は
[cloud42-labo/brain](https://github.com/cloud42-labo/brain) の `notes/scanhunt-concept.md` を参照。
