# AFP Android版｜Google Driveデータモデルと保存方針

Notion `AFP-02-T01`。`AFP-EPIC-02`（Android化と本人所有の長期記憶基盤を成立させる）の方針
（My Drive=ユーザー可視の正本、appDataFolder=内部キャッシュ、raw音声既定OFF、声クローン
参照データは暗号化、OpenAI APIキーは端末へ配布しない）に従い、Androidアプリが会話記憶・
声関連データをGoogle Driveへ保存する際のデータモデルを設計する。

対象は設計のみ。実装は `AFP-02-T04`（Androidアプリ骨格とGoogle認証の試作）以降で行う。
長期記憶の文脈構成方式（直近/サマリー/プロフィールの組み立てロジック）は `AFP-02-T02`、
OpenAI APIキーを端末に置かない接続方式は `AFP-02-T03` のスコープであり、本ドキュメントは
その前提となるファイル配置・保存形式・暗号化・削除復元のみを定義する。

> **参照について**: 本ドキュメントはGoogle Drive API v3の公開仕様（`My Drive` /
> `appDataFolder` の責務分離、`drive.file` / `drive.appdata` スコープの挙動）に関する
> 既知の実装知識に基づく。この設計セッションの実行環境ではネットワークの組織ポリシーにより
> `developers.google.com` への到達がブロックされており、該当ページを本セッション内で
> 都度フェッチして一次確認することはできなかった。`AFP-02-T04`（実装着手時）で
> 以下の参照URLの内容を実際に開いて本ドキュメントとの齟齬がないか確認すること。
>
> - https://developers.google.com/workspace/drive/api/guides/appdata
> - https://developers.google.com/workspace/drive/api/guides/about-files
> - https://developers.google.com/workspace/drive/api/guides/api-specific-auth

## 1. My Drive専用フォルダとappDataFolderの責務分離

| | My Drive専用フォルダ | appDataFolder |
|---|---|---|
| 可視性 | ユーザーがDrive UI/他アプリから閲覧・手動バックアップ・エクスポート可能 | ユーザーには不可視。作成元アプリ以外からもアクセス不可 |
| 役割 | 会話記憶・声データ・プロフィールの**正本** | 正本を指すインデックス、同期状態、端末非依存メタデータの**キャッシュ** |
| 必要スコープ | `drive.file`（アプリがDrive APIまたはPickerで作成・開いたファイルのみにアクセス。ユーザーの他のDriveファイルは不可視） | `drive.appdata`（専用の制限付きスコープ） |
| 保存先 | `My Drive` 直下にアプリ専用フォルダ（例: `AI Family Partner`）を1つ作成し、その配下にサブフォルダを持つ | 特殊フォルダID `appDataFolder` を親として直接ファイルを作成（ユーザー側にサブフォルダ階層は見えない） |
| 保存容量 | ユーザーのDrive容量を消費（想定通り。正本データのため） | 同じくユーザーのDrive容量を消費するが、用途はインデックス程度の小容量に限定する |
| 削除時の扱い | ユーザーがDrive側から直接削除・移動できてしまう（正本の性質上許容する） | アプリ経由でのみ操作されるため誤操作リスクは低い |

### フォルダ構成（My Drive側）

```
My Drive/
└── AI Family Partner/              # アプリ専用フォルダ（drive.fileスコープで作成）
    ├── conversation/
    │   └── {user_id}/
    │       └── {yyyy-mm-dd}.jsonl  # その日の直近会話ログ
    ├── profile/
    │   └── {user_id}.json          # 人物プロフィール（1ユーザー1ファイル）
    ├── summary/
    │   └── {user_id}.json          # 長期サマリー（増分更新・1ユーザー1ファイル）
    └── voice/
        └── {user_id}.enc           # 声クローン参照データ（暗号化済みバイナリ）
```

`{user_id}` はアプリ内で発行する家族メンバー識別子（Googleアカウントのsubとは独立に、
1台のアプリ内で複数の家族メンバーを区別するための値）。`AFP-01-T01` で導入した
「利用者ごとの分離」の方針をAndroid版でもフォルダ単位で引き継ぐ。

### appDataFolder側の内容

```
appDataFolder/
└── index.json   # My Drive側フォルダ・各ファイルのfile ID索引、最終同期時刻、
                 # スキーマバージョンのみ。暗号鍵やそのラップ済みメタデータは
                 # 一切含まない（鍵はAndroid Keystoreのみに存在し、§3参照）
```

`index.json` はMy Drive側ファイルのfile IDをキャッシュする目的のみ。信頼できる唯一の
情報源（SoT）は常にMy Drive側であり、`index.json` が失われた場合はMy Drive専用フォルダを
名前で再検索して再構築できる設計とする（§4参照）。

## 2. 保存形式

| 種別 | 形式 | 1ファイルの単位 | 理由 |
|---|---|---|---|
| conversation | JSON Lines (`.jsonl`、暗号化なし） | ユーザー×日 | 日付でファイルを分けることで1回の書き込みで送受信する内容量を日次サイズに制限し、無限肥大化を防ぐ |
| profile | 単一JSON (`.json`、暗号化なし） | ユーザー単位 | 更新頻度が低く、全体を読み書きしても問題ない小さな構造化データ |
| summary | 単一JSON (`.json`、暗号化なし） | ユーザー単位 | `AFP-02-T02`で設計する長期記憶の集約結果を保持する器。増分更新（直近の要約を追記し古いものを圧縮）する運用は`AFP-02-T02`側の設計対象 |
| voice | 暗号化バイナリ (`.enc`) | ユーザー単位 | OmniVoiceの声クローン参照データ（`AFP-01-T01`で一時ファイル化した旧 `active_voice.pt` 相当）をそのまま暗号化して保存する |

各JSON/JSONLファイルの内部スキーマ（フィールド定義）は、conversationは`AFP-02-T02`、
summaryは同じく`AFP-02-T02`で確定する長期記憶方式に従って決める。本ドキュメントは
「どこに・どの形式の箱を置くか」までを定義し、箱の中身のスキーマは踏み込まない。

### 書き込み方式（conversationのjsonl）

Drive APIにはバイト単位の追記APIが無く、`files.update`のメディアアップロードは常に
ファイル内容全体を置き換える。そのため「末尾への真の追記」はできない。実際の書き込みは
次のアプリ層の手順で行う。

1. 当日分のjsonlの内容をアプリ内メモリ（またはローカルDB）にバッファとして保持する。
2. 各ターン終了時、またはアプリがバックグラウンドに回るタイミングで、バッファ全体を
   `files.update`（既存ファイルがあれば）または `files.create`（当日分が未作成なら）で
   丸ごとアップロードする（read-modify-writeであり、真のバイト追記ではない）。
3. 1ファイルの単位をユーザー×日に区切っているため、1回のアップロードで送信する内容量は
   その日の会話量に収まり、無期限に肥大化したファイルを毎回全置換する事態を避けられる。

## 3. 暗号化方式

`AFP-EPIC-02`の方針「声クローン参照データは暗号化する」「OpenAI APIキーをAndroidへ
持たせない」に基づき、暗号化はAndroid端末内で完結させ、鍵をDriveにもバックエンドにも
一切送らない。

- **鍵**: Android Keystoreで生成するAES-256-GCM鍵（`StrongBox`/TEEが利用可能な端末では
  ハードウェアバック鍵を優先し、無ければソフトウェア鍵にフォールバックする）。
  鍵はKeystore内に閉じ、エクスポート不可（`setUserAuthenticationRequired`は要件確認の上
  `AFP-02-T04`で決定、本ドキュメントでは必須としない）。
- **対象**: `voice/{user_id}.enc` のみを暗号化対象とする（Epic方針で明記されているのは
  声クローン参照データのみ）。`conversation` / `profile` / `summary` は暗号化しない
  （平文JSON/JSONLのまま保存する）。
  - **理由（当初案からの修正）**: 当初は`conversation`/`profile`/`summary`も同じ
    Android Keystore鍵で暗号化する案を検討したが、下記「鍵の非持ち出し方針」（鍵は
    Android Keystore内に閉じ、Driveにも端末間同期にも出さない）と両立しない。
    `voice`と同じ鍵で暗号化すると、これらも`voice`と同様に端末依存となり、§4で
    求める「アプリ再インストール後も`conversation`/`profile`/`summary`は復元できる」
    というAcceptance Criteriaと矛盾する（Codexレビュー指摘により判明）。
    これらを暗号化したまま複数端末間で復号可能にするには、鍵をDriveやバックエンドへ
    ラップして保管する仕組みが別途必要になり、`Minimum Solution`（新規サービス・
    鍵管理基盤を作らない）に反する。よって本Taskのスコープでは`voice`以外は暗号化せず、
    保護はGoogleアカウント認証＋`drive.file`スコープ（このアプリが作成したファイルにしか
    アクセスできない）というDrive API自体のアクセス制御に委ねる。
    複数端末間でも`voice`まで含めて復元可能にしたい場合は、鍵のバックアップ方式
    （例: ユーザー設定のリカバリフレーズでラップした鍵をappDataFolderへ保管する等）を
    別Taskとして設計する。
- **方式**: AES-256-GCMでファイル単位に暗号化し、`{nonce}{ciphertext}{tag}`をそのまま
  Drive上のバイナリとして保存する（コンテナ形式は自由、OmniVoice側の読み込みに影響しない
  よう`voice`のみ既存のプロンプトファイルをラップする形にする）。
- **鍵の非持ち出し方針**: 鍵はAndroid Keystoreのみに存在し、Driveにも端末間同期にも
  乗せない。これにより「同一Googleアカウントで別端末からログインしても、鍵を再発行しない
  限り過去の暗号化データは復号できない」という制約が生じる（§4で復元方針として明記）。
  複数端末間の鍵共有が必要になった場合は、別Taskとして改めて設計する（本Taskのスコープ外。
  `Minimum Solution`＝新規サービスを作らない方針に合わせ、最小構成では端末ローカル鍵の
  範囲に留める）。

## 4. 削除・復元方針

### 削除

ユーザーがアプリ内の「データを削除」操作を行った場合:

1. My Drive専用フォルダ（`AI Family Partner`）を `files.update` で `trashed: true` に
   設定し、Google Driveの標準のゴミ箱へ移動する（`files.delete`は対象を即時・恒久的に
   削除しゴミ箱の猶予期間を経由しないため使わない。`trashed: true`なら配下の子ファイルも
   まとめてゴミ箱表示上は非表示になり、ユーザーがDrive UIから任意の保持期間内に取り消せる）。
2. `appDataFolder` 配下の `index.json` も同様に `files.update` で `trashed: true` にする
   （`appDataFolder`はユーザー非表示のため取り消し操作自体は提供しないが、処理を統一する）。
3. Android Keystore側の鍵も破棄する（Keystoreからのキー削除）。

Drive側の「ゴミ箱からの完全削除までの猶予期間」はGoogle Driveの標準動作（ユーザー設定の
ゴミ箱保持期間）に従い、アプリ側で追加の猶予処理は実装しない。ゴミ箱を経由しない
即時・恒久的な削除が必要になった場合（例: ユーザーが「完全に消去する」ことを明示的に
求めた場合）は、ゴミ箱へ移動した上でユーザーに猶予期間中の取り消し手段があることを
明示してから、別途`files.delete`による恒久削除を行う設計とする（本Taskでは既定の削除
操作としては採用しない）。

### 復元（アプリ再インストール時）

1. Googleアカウント認証後、まず `appDataFolder` の `index.json` を読み出す。
2. `index.json` が取得できた場合はそこに記録されたfile IDをそのまま使う。
3. `index.json` が無い/読めない場合（＝appDataFolder側だけ失われた、または初回復元）は、
   `files.list` で `name = 'AI Family Partner' and 'root' in parents and trashed = false`
   を条件にMy Drive専用フォルダを名前検索し、見つかればそのfile IDから再度
   `conversation` / `profile` / `summary` / `voice` の各サブフォルダ・ファイルを辿って
   `index.json` を再構築する。
4. `conversation` / `profile` / `summary` はそのまま復元できる。
5. `voice` は暗号化鍵が旧端末のAndroid Keystoreにしか存在しないため、新端末（または
   アプリ再インストール後の新しいKeystoreエントリ）では復号できない。この場合はUI上で
   「声の再登録が必要です」と明示し、`voice/{user_id}.enc` を新しい鍵で上書きする
   声登録フローへ誘導する（`AFP-01-T01`で確立した本人同意フローを踏襲する）。

### 復元テスト手順（`AFP-02-T04`実装時に実機で確認する）

1. アプリをアンインストールする。
2. アプリを再インストールし、同じGoogleアカウントで認証する。
3. `appDataFolder` の `index.json` を消した状態（初回復元の想定）でも、名前検索で
   `AI Family Partner` フォルダが見つかり、`conversation` / `profile` / `summary` が
   復元され会話が継続できることを確認する。
4. `voice` は復号できず、再登録を促すUIが表示されることを確認する。
5. 再登録後、新しい `voice/{user_id}.enc` がMy Drive側で上書きされることを確認する。

## まとめ（Acceptance Criteriaとの対応）

- My Drive専用フォルダとappDataFolderの責務 → §1
- conversation/profile/summary/voiceの保存形式 → §2
- 暗号化 → §3
- 削除・復元方針 → §4
- `AFP-02-T02`（長期記憶の文脈構成方式）・`AFP-02-T03`（OpenAI APIキー管理）とは、
  ファイル配置と暗号化という下位レイヤーのみを扱うことで役割を分離し、内容の矛盾は無い。
