# 秘密情報・設定値の取り扱い方針（SH-02-S04）

由来: Notion `SH-02-S04｜APIキー・権限・環境設定`

Scanhuntは個人のGoogle Workspace上で動く単一ユーザーMVP。専用のシークレット管理基盤
（Secret Manager等）は導入せず、**「Notion・GitHubに秘密情報を書かない」ことだけを
最低限のルールとして徹底する。**

## 設定値一覧と置き場所

| 設定値 | 何に使うか | 置き場所 | 誰が入力するか |
|---|---|---|---|
| Gemini APIキー | パッケージ画像のAI解析（既存実装） | ブラウザの `localStorage` のみ | ユーザー（初回起動時に `prompt()`） |
| Apps Script Web App URL | `apps-script-api.md` のAPIエンドポイント | ブラウザの `localStorage` のみ | ユーザー（設定画面で入力。下記参照） |
| Apps Script API Key | 上記APIの認証（`Code.gs` の `checkApiKey_`） | サーバー側: Script Properties<br>クライアント側: `localStorage` | サーバー側はデプロイ時に自分で生成・設定。クライアント側は設定画面で入力 |
| Spreadsheet ID | Apps Scriptがどのシートを読み書きするか | **サーバー側のみ**（Script Propertiesの `SPREADSHEET_ID`。`Code.gs` が `SpreadsheetApp.openById()` で明示的に開く） | サーバー側はデプロイ時に自分で（このSpreadsheet自身のIDを）設定。該当箇所: `apps-script-api.md` デプロイ手順 |
| Drive Folder ID | 画像・ログの保存先（`/Scanhunt/...`） | **サーバー側のみ**（`Code.gs` の `getOrCreateFolderPath_` がパス名から都度解決し、IDを保持しない） | 該当なし |

**Spreadsheet IDとDrive Folder IDはそもそもPWA側に持たせない。** Spreadsheet IDはコンテナ
バインドスクリプトのScript Propertiesにサーバー側だけで設定し（`SpreadsheetApp.getActiveSpreadsheet()`
はWebアプリの実行では`null`を返しうるため使わない。設定理由の詳細は`apps-script-api.md`）、
Driveフォルダもパス名（`Scanhunt/logs` 等）から都度解決する設計にしたため、この2つはPWA・
Notion・GitHubのどこにも登場しない。これにより「安全に扱う」べき対象は実質2つ
（Gemini APIキー、Apps Script API Key）と、公開情報であるApps Script URLの3つに絞られる。

## localStorageの利用範囲

- 上記の3値（Gemini APIキー、Apps Script URL、Apps Script API Key）のみを保存する。
  ソースコード・Notion・GitHubのいずれにも書かない。
- 初回起動時、いずれかが未設定であれば設定画面（または既存実装と同じ `prompt()` 方式）で
  入力を促す。既存のGemini APIキー入力パターンをそのまま踏襲する。
- **localStorageは端末・ブラウザ単位。** 別端末で使う場合は再入力が必要になる
  （MVPでは許容する。複数端末対応は将来課題）。
- `is_training_candidate` の判定に使う個人情報等、上記3値以外の秘密情報はlocalStorageに
  保存しない。撮影した画像・解析結果はDrive/Spreadsheetへ送信済みのものを正とし、
  端末側に永続キャッシュしない。

## Notion / GitHubに秘密情報を書かないルール

- 上記3値は、チケットのResult・PR説明・コミットメッセージ・スクリーンショットの
  いずれにも**値そのものを書かない**。
- 動作確認の証跡を残す場合は、値をマスクする（例: `AIza***`／`sk-***`）か、
  「設定済みであることを確認した」という事実だけを記録する。
- Apps ScriptのAPI Keyは `Code.gs` にハードコードしない。必ず
  `PropertiesService.getScriptProperties()` 経由で読む（`apps-script-api.md` の
  デプロイ手順どおり）。
- 誤って秘密情報をNotion・GitHubへ書いてしまった場合は、値を無効化（Apps Script側の
  `API_KEY` を再生成、Gemini APIキーを再発行）した上で、該当箇所を編集除去する。
  Git履歴に残る場合はPostmortemへ記録し（Operating Guide §12.3）、再発防止策を検討する。

## エラー時のユーザー表示

3値それぞれの未設定・不正時に、原因を推測できる文言をユーザーへ表示する。
汎用的な「エラーが発生しました」だけで止めない。

| 状況 | 表示文言（例） | 次の一手 |
|---|---|---|
| Gemini APIキー未設定 | 「AI解析にはGemini APIキーの設定が必要です」 | 設定画面へ誘導し再入力させる（既存実装のフォールバック動作を踏襲） |
| Apps Script URL未設定 | 「保存先の設定が完了していません（Apps Script URL）」 | 設定画面へ誘導 |
| Apps Script API Key未設定・不一致（`unauthorized`） | 「保存に失敗しました（認証エラー）。設定を確認してください」 | 設定画面で値を再確認させる。**サーバー側のAPI_KEY自体は表示しない** |
| `sheet_not_found` / `sheet_not_initialized` | 「保存先シートの準備が完了していません」 | `SH-02-S01` が未完了である旨を示し、撮影データはローカルに保持したまま再送を促す（データを失わない） |
| ネットワークエラー・タイムアウト | 「保存に失敗しました。通信環境を確認して再試行してください」 | 再試行ボタンを出す。画像・解析結果はDrive保存済み（`createProductImage`/`createAIJob` が先行するため）であれば再送のみで復旧できる設計にする |
| `missing_fields`（実装バグ） | 「保存に失敗しました（不正なデータ）」 | ユーザー操作では回避不可。開発側でログ確認が必要な旨を残す（`error.message` はコンソールログにのみ出力し、画面には出さない） |

`apps-script-api.md` の `error.code` を上記表示の分岐キーとして使う。`error.message`
（Apps Script側が生成する詳細メッセージ）はデバッグ用としてコンソールログにのみ出し、
画面には出さない（内部実装の詳細をエンドユーザーに見せない）。

## 積み残し・要確認事項

1. **Apps Script API Keyのローテーション手順は未定義。** 漏洩時にScript Propertiesを
   更新するだけで良いか、PWA側の再入力導線が要るかは、実際の運用で困ってから決める
   （MVPは単一ユーザーのため優先度低）。
2. **設定画面のUIは未実装。** 現状は既存のGemini APIキーと同じ `prompt()` ベースを
   踏襲する想定だが、3値まとめて入力できる設定画面にするかは `SH-04` 系のUI実装時に判断する。
