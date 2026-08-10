# Prototype Source Manifest

Experimental 登録時に受領した実装プロトタイプの情報。

| 項目 | 値 |
|---|---|
| Product | 人財ポートフォリオマネジメント |
| Version | v0.0.0 |
| Original source file | `index(1).html` |
| Original format | 単一 HTML |
| Original size | 166,483 bytes |
| Original SHA-256 | `81dea885874dd05c57197fe44338ad41e5ae34896c58df0f9a56a904f1b3a6d1` |
| HTML title | 人財ポートフォリオマネジメント |
| APP_VERSION | `0.0.0` |

## Experimental での格納形式

GitHub コネクタ経由で会話添付の 166KB HTML を1ファイルのまま転送できないため、PR内では転送用パッケージとして以下の形で格納している。

- `index.html` — ローダー
- `source-parts/01.js` 〜 `07.js` — 元HTMLを deterministic gzip（mtime=0）で圧縮し、Base64化したペイロード
- `index.html` は7パーツを連結・展開し、元HTMLをブラウザ上で復元して実行する
- 外部API・CDNへの依存は追加していない

ローカル検証では、7パーツを連結・Base64デコード・gzip展開した結果が **166,483 bytes** となり、元の `index(1).html` とバイト単位で一致した。復元後の SHA-256 も `81dea885874dd05c57197fe44338ad41e5ae34896c58df0f9a56a904f1b3a6d1` で一致している。

> 製品仕様上のソース・オブ・トゥルースは「単一HTML」。この分割は Experimental へ登録する際の転送制約を回避するための格納形式であり、プロダクト仕様そのものを変更するものではない。

## 実装上の主要構造

- 7フェーズ：事業戦略 → 人財レントゲン → 組織設計 → 部門別ギャップ → 投資配分 → 経営（毎年） → 結果
- 店舗運営部、商品部、管理本部、EC・デジタル部、経営の5部門
- 内部育成、新卒、中途エージェント、ヘッドハント、リファラル、内部異動の6調達経路
- 人事アーキテクチャ、組織再編、報酬水準、現場対応レバー
- 財務影響、後継者育成、エンゲージメント、人心掌握、10年後持続可能性投影
- AI分析用の経営レポート生成
