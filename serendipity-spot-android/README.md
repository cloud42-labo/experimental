# Serendipity Spot (Android)

[serendipity-spot](../serendipity-spot/) にあったvibe codingのHTML試作（地図タップでスポット登録
→近づいたら通知）を、実機のAndroidで動くネイティブアプリにした版。

## この版でやっていること

- **Googleアカウントでサインイン**。認証は Credential Manager（Sign in with Google）、
  スプレッドシートを読み書きするためのスコープ取得は AuthorizationClient と、役割を分けている
  （旧 `GoogleSignIn` API はGoogleがサポート終了を明示しているため使っていない）
- スポットは**自分のGoogleドライブ上のスプレッドシート**（`Serendipity Spot`）に保存・管理する。
  初回サインイン時にアプリが自動でスプレッドシートを作成する
- 地図（Google Maps SDK）をタップしてスポットを登録
- **バックグラウンドでの近接通知**（Geofencing API）。アプリを閉じていても、登録したスポットの
  半径150m以内に入ると通知＋バイブで知らせる
- 端末再起動後もジオフェンスを張り直す（ローカルキャッシュから復元）

## 元のHTML版からの変更点・省略した機能

- 住所・スポット名でのテキスト検索（Nominatim）は今回省略。地図を直接タップして登録する形にした
- 地図はOpenStreetMap→Google Maps SDK for Androidに変更（ユーザーの回答による）
- 通知は「アプリを開いている間だけ」ではなく、Geofencingによる常時バックグラウンド監視にした

## セットアップ（初回のみ・あなたのGoogle Cloudプロジェクトが必要）

このアプリはあなた自身のGoogle CloudプロジェクトでAPIキー/OAuthクライアントを発行して使う前提。
コードには何も埋め込まれていない。

### 1. Google Cloud Consoleでプロジェクトを用意する

1. https://console.cloud.google.com/ でプロジェクトを作成（または既存のものを使う）
2. 「APIとサービス」→「ライブラリ」で以下を有効化する
   - **Google Sheets API**
   - **Google Drive API**
   - **Maps SDK for Android**

### 2. OAuth同意画面

「APIとサービス」→「OAuth同意画面」で外部/テストのまま、自分のGoogleアカウントを
「テストユーザー」に追加する（個人利用なので公開審査は不要）。

### 3. OAuthクライアントID（Android用）を発行

「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuthクライアントID」
→ アプリケーションの種類は **Android** を選び、以下を設定する。

- パッケージ名: `com.cloud42labo.serendipityspot`
- SHA-1証明書フィンガープリント: 下記の方法で取得する

**Android Studio から取るのが確実**（OS問わず、`keytool` のパスを気にしなくてよい）。
このディレクトリをAndroid Studioで開き、下部の Terminal タブで:

```sh
./gradlew signingReport      # Windows は .\gradlew signingReport
```

出力の `Variant: debug` の項にある `SHA1:` の行（`A1:B2:...` 形式）を使う。

`keytool` を直接叩く場合は次の通り。デバッグ用キーストアは初回ビルド時に作られるため、
一度もビルドしていないとファイルが無い。

```sh
# macOS / Linux
keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android -keypass android

# Windows (PowerShell)
keytool -list -v -keystore "$env:USERPROFILE\.android\debug.keystore" -alias androiddebugkey -storepass android -keypass android
```

Android用OAuthクライアントはパッケージ名+SHA-1で識別されるため、このクライアントIDを
コード側に書く必要はない。

**デバッグ用キーストアは開発マシンごとに異なる。** 別のPCでビルドしたり、
クラウドセッションでビルドしたAPKを実機に入れたりする場合は、そのマシンのSHA-1も
同じOAuthクライアントに追加登録しないとサインインが失敗する。

### 3-2. OAuthクライアントID（ウェブアプリケーション用）も発行する

Credential Manager のサインインには、Android用とは**別に**「ウェブ アプリケーション」型の
クライアントID（server client ID）が要る。同じ「認証情報を作成」→「OAuthクライアントID」から、
アプリケーションの種類に **ウェブ アプリケーション** を選んで作る。
リダイレクトURIやオリジンの設定は不要で、発行されたクライアントID文字列だけを使う。

これは5.で `local.properties` の `GOOGLE_SERVER_CLIENT_ID` に設定する。
**Android型のクライアントIDを入れても動かない**ので注意。

### 4. Maps SDK用のAPIキーを発行

「認証情報を作成」→「APIキー」で発行し、「キーの制限」で
- アプリケーションの制限: Androidアプリ → パッケージ名 + 上と同じSHA-1を登録
- APIの制限: Maps SDK for Android のみに絞る

### 5. ローカルに設定を書く

```sh
cp local.properties.example local.properties
```

`local.properties` に以下2つを設定する（`.gitignore` 対象なのでコミットされない）。

- `MAPS_API_KEY` — 4.で発行したAPIキー
- `GOOGLE_SERVER_CLIENT_ID` — 3-2.で発行したウェブアプリケーション型のクライアントID

## ビルド・実行

Android Studio でこのディレクトリ（`serendipity-spot-android/`）を開いて実行するのが確実。
CLIの場合:

```sh
./gradlew assembleDebug
```

**Claude Code のクラウドセッションでは、既定のままだとビルドできない。** 原因は
`dl.google.com` が環境の通信許可リストに入っていないことの一点で、下記の設定で解消できる。

### Claude Code のクラウドセッションでビルドできるようにする

`dl.google.com` は Google Maven（Android Gradle Plugin・AndroidX・Play Services）と
Android SDK 本体の**両方**の配布元。既定の Trusted 許可リストには `developer.android.com` は
あるが `dl.google.com` は無いため、プロキシが CONNECT に 403 を返して依存解決が全部失敗する。
`maven.google.com` は許可されているが中身は `dl.google.com` への301リダイレクトなので迂回にならない。

1. [claude.ai/code](https://claude.ai/code) のメッセージ入力欄の上にある雲アイコン（環境セレクタ）を開く
2. 環境の歯車アイコン →「Network access」を **Custom** に変更
3. Allowed domains に `dl.google.com` を追加
4. **「Also include default list of common package managers」にチェックを入れる**
   （外すと Maven Central・npm 等も一緒に塞がる）
5. 同じダイアログの「Setup script」に [`scripts/setup-android-sdk.sh`](scripts/setup-android-sdk.sh)
   の中身を貼る（Android SDK はプリインストールされていないため）

Gradle 本体・Maven Central・plugins.gradle.org は既定で許可済みなので、追加は `dl.google.com` だけでよい。

設定を変えると環境キャッシュが再構築され、次に始めたセッションから `./gradlew assembleDebug`
が通るようになる（実行中のセッションには反映されない）。

**現時点でこのビルドは未検証。** 上記の設定を入れたセッション、または Android Studio が動く
PC/Mac で最初のビルド確認をしてほしい。

## 実機で使うときの注意

- 初回起動時に位置情報の許可（使用中のみ）→続けてバックグラウンド許可のダイアログが出る。
  「常に許可」にしないとアプリを閉じた後の通知が届かない
- Android 13+では通知の許可も別途必要
- 端末メーカーによっては省電力設定でバックグラウンドの位置情報監視が止められることがある
  （Geofencing自体はOSのバッチ処理なのでこの実装ではさほど強い影響は受けない想定だが、
  実機で通知が来ない場合はまずここを疑う）
- ジオフェンスは1アプリ最大100件（Android/Google Playの制限）。それを超える分は登録が古い順に
  対象外になる

## データについて

- スプレッドシートは `drive.file` スコープで作成するため、このアプリが作った/開いたファイル
  にしかアクセスできない（ユーザーのDrive全体は見えない）
- スプレッドシート名は固定で `Serendipity Spot`。再インストール後もGoogleアカウントに
  紐づく形でこのファイルを探しにいくので、同じシートを使い続けられる
- シートの列: `id | lat | lng | title | memo | radiusMeters | createdAt`
