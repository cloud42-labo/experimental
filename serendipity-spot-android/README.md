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

この設定を入れたクラウドセッションでのビルド、および Windows + Android Studio での
実機ビルドは確認済み。

## PCなしで最新版を端末に入れる（GitHub Actions）

外出先など、PCが手元に無い状態で修正を試したいとき用。`main` に変更が入るたびに
[ワークフロー](../.github/workflows/serendipity-spot-android.yml)がAPKをビルドし、
`dev` タグのプレリリースに貼り直す。**ダウンロードURLは毎回同じ**なので、スマホの
ブラウザでこれを開けばよい。

```
https://github.com/cloud42-labo/experimental/releases/download/dev/app-debug.apk
```

### 必要な準備（初回のみ）

**1. GitHub のシークレットを設定する**（Settings > Secrets and variables > Actions）

| 名前 | 内容 |
| :--- | :--- |
| `SERENDIPITY_DEBUG_KEYSTORE_BASE64` | デバッグ署名鍵を `base64 -w0` にかけた文字列。必須 |
| `SERENDIPITY_GOOGLE_SERVER_CLIENT_ID` | ウェブ アプリケーション型のクライアントID。必須 |
| `SERENDIPITY_MAPS_API_KEY` | Maps のAPIキー。任意（未設定だと地図が灰色になるだけ） |

**2. CIの鍵のSHA-1をOAuthクライアントに登録する**

CIが使う鍵は手元の `~/.android/debug.keystore` とは別物になるため、そのままでは
**サインインだけが失敗する**（ビルドも起動も地図も通るので紛らわしい）。
Cloud Console でAndroid型のOAuthクライアントを**もう1つ**作り、CIの鍵のSHA-1を登録する。
同じパッケージ名で複数登録してよい。

CIの鍵のSHA-1は、Actions のログの `Show signing fingerprint` ステップに出る。

手元の `debug.keystore` をそのままシークレットに入れれば、この2番目の登録は不要。

### 端末側

- 提供元不明のアプリのインストールを許可する（ブラウザに対して1回だけ聞かれる）
- **署名が違うAPKは上書きインストールできない。** PCで入れたアプリが残っている場合は
  一度アンインストールしてから入れる。スポットはスプレッドシート側にあるので、
  サインインし直せば元に戻る

## 移動せずにジオフェンス通知を試す

実際に現地へ行かなくても、端末のモックロケーションで発火させられる。

1. Google Play で位置偽装アプリを入れる（"Fake GPS location" など）
2. 「設定」→「開発者向けオプション」→「**仮の現在地情報アプリを選択**」でそのアプリを指定
3. 位置偽装アプリで、登録済みスポットから**十分離れた地点**を指定して開始する
4. Serendipity Spot を起動し、スポットが読み込まれた状態にする（ジオフェンスが張られる）
5. アプリを閉じる
6. 位置偽装アプリで、スポットの座標へ移動する

ジオフェンスは「外から中への遷移」で発火するので、**最初に外にいることが必要**。
スポットの真上から始めると何も起きない。

反応しない場合は、位置情報の権限が「常に許可」か、端末の省電力設定でアプリが
制限されていないかを先に確認する。

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
