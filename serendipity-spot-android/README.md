# Serendipity Spot (Android)

[serendipity-spot](../serendipity-spot/) にあったvibe codingのHTML試作（地図タップでスポット登録
→近づいたら通知）を、実機のAndroidで動くネイティブアプリにした版。

## この版でやっていること

- **Googleアカウントでサインイン**（Google Sign-In）
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
- SHA-1証明書フィンガープリント: デバッグ用は次のコマンドで取得できる

  ```sh
  keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android -keypass android
  ```

Android用OAuthクライアントはパッケージ名+SHA-1で識別されるため、コード側にクライアントID
文字列を埋め込む必要はない。

### 4. Maps SDK用のAPIキーを発行

「認証情報を作成」→「APIキー」で発行し、「キーの制限」で
- アプリケーションの制限: Androidアプリ → パッケージ名 + 上と同じSHA-1を登録
- APIの制限: Maps SDK for Android のみに絞る

### 5. ローカルに設定を書く

```sh
cp local.properties.example local.properties
```

`local.properties` の `MAPS_API_KEY` に4.で発行したAPIキーを設定する
（`local.properties` は `.gitignore` 対象なのでコミットされない）。

## ビルド・実行

Android Studio でこのディレクトリ（`serendipity-spot-android/`）を開いて実行するのが確実。
CLIの場合:

```sh
./gradlew assembleDebug
```

**この開発コンテナではAndroid SDKと `dl.google.com`（Android/Play Servicesの依存関係の取得元）
へのネットワークアクセスがどちらも塞がれているため、ここではビルド確認ができていない。**
Android StudioがインストールされたPC/Macで最初のビルド確認をしてほしい。

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
