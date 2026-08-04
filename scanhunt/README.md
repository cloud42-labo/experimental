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
自動シャッター）のUIのみで、AI解析部分はモックデータ。

- [ ] Gemini API連携（表裏2枚の画像 → JSON構造化データ抽出）
- [ ] 抽出結果の永続化（マイ・レシピ帳のデータ保存）
- [ ] JANコード重複時のフィードバックUI

## データ構造（想定）

```json
{
  "gtin_jan": "4900000000000",
  "product_name": "商品名",
  "brand": "ブランド/メーカー名",
  "category": "冷凍食品",
  "temperature_zone": "frozen",
  "cooking_instructions": {
    "microwave": { "wattage_500w": "3分30秒", "wattage_600w": "3分" },
    "pan_fry": "水50mlを入れてフタをし5分",
    "other_notes": "調理上の注意点"
  },
  "nutrition": { "calories_kcal": 350, "protein_g": 12.5, "fat_g": 15.0, "carbs_g": 40.0 },
  "allergens": ["小麦", "卵", "大豆"]
}
```

## 技術スタック（今後の実装方針）

- フロントエンド: React / Next.js (TypeScript) + Tailwind CSS + Lucide Icons
- カメラスキャン: HTML5 WebRTC (react-webcam 等)
- AI OCR/解析: Gemini API（マルチモーダル）

詳しい検討の経緯（カテゴリ選定・UXフロー設計・vibe codingの進め方）は
[cloud42-labo/brain](https://github.com/cloud42-labo/brain) の `notes/scanhunt-concept.md` を参照。
