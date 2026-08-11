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

`index.html` として元HTMLをそのまま単一ファイルで格納している。サイズ・SHA-256とも
上表の値と一致することを確認済み。

> 過去の経緯: 初回登録時（PR #78）は GitHub コネクタ経由で会話添付の166KB HTMLを
> 1ファイルのまま転送できないという制約から、deterministic gzip（mtime=0）+ Base64で
> 7分割したペイロード（`source-parts/01.js`〜`07.js`）をブラウザ上で復元・実行する
> ローダー方式を採った。しかし実際には分割・連結の過程でペイロードが破損しており
> （CRC32チェック失敗、ファイル冒頭14%付近から文字化け）、「バイト単位で一致した」
> という当時の記述は誤りだった。起動不能な状態のままオーナーへ差し戻し、
> 元ファイルをセッションへ直接アップロードしてもらう形で再登録し、この分割方式は廃止した。

> 製品仕様上のソース・オブ・トゥルースは「単一HTML」。今回の再登録はこの原則どおり、
> 元ファイルをそのまま格納する形に戻したもの。
