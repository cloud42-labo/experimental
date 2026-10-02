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
                 # スキーマバージョン、暗号化鍵のラップ済みメタデータ（鍵本体は含まない）
```

`index.json` はMy Drive側ファイルのfile IDをキャッシュする目的のみ。信頼できる唯一の
情報源（SoT）は常にMy Drive側であり、`index.json` が失われた場合はMy Drive専用フォルダを
名前で再検索して再構築できる設計とする（§4参照）。

## 2. 保存形式

| 種別 | 形式 | 1ファイルの単位 | 理由 |
|---|---|---|---|
| conversation | JSON Lines (`.jsonl`) | ユーザー×日 | 追記のみで済み、長期化してもファイル全体を読み直さずに末尾追記できる。日付ロールオーバーで無限肥大化を防ぐ |
| profile | 単一JSON (`.json`) | ユーザー単位 | 更新頻度が低く、全体を読み書きしても問題ない小さな構造化データ |
| summary | 単一JSON (`.json`) | ユーザー単位 | `AFP-02-T02`で設計する長期記憶の集約結果を保持する器。増分更新（直近の要約を追記し古いものを圧縮）する運用は`AFP-02-T02`側の設計対象 |
| voice | 暗号化バイナリ (`.enc`) | ユーザー単位 | OmniVoiceの声クローン参照データ（`AFP-01-T01`で一時ファイル化した旧 `active_voice.pt` 相当）をそのまま暗号化して保存する |

各JSON/JSONLファイルの内部スキーマ（フィールド定義）は、conversationは`AFP-02-T02`、
summaryは同じく`AFP-02-T02`で確定する長期記憶方式に従って決める。本ドキュメントは
「どこに・どの形式の箱を置くか」までを定義し、箱の中身のスキーマは踏み込まない。

## 3. 暗号化方式

`AFP-EPIC-02`の方針「声クローン参照データは暗号化する」「OpenAI APIキーをAndroidへ
持たせない」に基づき、暗号化はAndroid端末内で完結させ、鍵をDriveにもバックエンドにも
一切送らない。

- **鍵**: Android Keystoreで生成するAES-256-GCM鍵（`StrongBox`/TEEが利用可能な端末では
  ハードウェアバック鍵を優先し、無ければソフトウェア鍵にフォールバックする）。
  鍵はKeystore内に閉じ、エクスポート不可（`setUserAuthenticationRequired`は要件確認の上
  `AFP-02-T04`で決定、本ドキュメントでは必須としない）。
- **対象**: `voice/{user_id}.enc` を必須の暗号化対象とする（Epic方針で明記）。
  `conversation` / `profile` / `summary` は会話内容という性質上、同じAndroid Keystore鍵を
  用いて同様に暗号化する設計とする（Epic方針に明記はないが、本人の会話・プロフィールという
  機微情報をMy Drive上に平文で置かない方が安全側であり、追加の新規サービスや鍵管理基盤を
  要しないため採用する。鍵は声データと共用し、ユーザーあたり1鍵とする）。
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

1. My Drive専用フォルダ（`AI Family Partner`）をDrive API `files.delete` で削除する
   （Drive APIの仕様上、フォルダ削除で配下の子ファイルも連鎖的にゴミ箱へ移動/削除される）。
2. `appDataFolder` 配下の `index.json` も同様に削除する。
3. Android Keystore側の鍵も破棄する（Keystoreからのキー削除）。

Drive側の「ゴミ箱からの完全削除までの猶予期間」はGoogle Driveの標準動作（ユーザー設定の
ゴミ箱保持期間）に従い、アプリ側で追加の猶予処理は実装しない。

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
