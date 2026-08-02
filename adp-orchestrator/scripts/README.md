# Windows起動Script

`start-windows.ps1`は、Windows資格情報マネージャーに保存したSlack Tokenを読み取り、ADP Orchestratorの子Python Processへだけ渡します。

## 前提

Windows資格情報マネージャーの「Windows 資格情報」に、次のGeneric Credentialが存在することを確認します。

| Target name | Passwordに保存する値 |
|---|---|
| `ADP_SLACK_BOT_TOKEN` | Slack Bot Token（`xoxb-`で始まる値） |
| `ADP_SLACK_APP_TOKEN` | Slack App-Level Token（`xapp-`で始まる値） |

TokenをPowerShellへ貼り付けたり、`.env`へ複製したりしません。Signing SecretはSocket Mode起動には使用しません。

## 起動

仮想環境を有効化し、`adp-orchestrator`ディレクトリで次を実行します。

```powershell
.\scripts\start-windows.ps1 `
  -ControlChannelId C0123456789 `
  -HumanRequestsChannelId C0123456790 `
  -DailyChannelId C0123456791
```

3つの値には、それぞれ次のSlack Channel IDを指定します。

- `#adp-control`
- `#adp-human-requests`
- `#adp-daily`

Channel IDは秘密情報ではありません。チャンネル名ではなく、`C`または`G`で始まるIDを指定します。

Pythonコマンドを明示する場合は、次のように指定します。

```powershell
.\scripts\start-windows.ps1 `
  -ControlChannelId C0123456789 `
  -HumanRequestsChannelId C0123456790 `
  -DailyChannelId C0123456791 `
  -PythonCommand .\.venv\Scripts\python.exe
```

## Secretの扱い

ScriptはTokenを次へ書き込みません。

- `.env`
- コマンドライン引数
- 標準出力
- Git

TokenはLauncher Processのローカル変数と、子Python Processの環境変数にだけ存在します。子Process終了後、Launcher側の参照と`ProcessStartInfo`内のTokenを削除します。

## エラー

資格情報が存在しない、Passwordが空、Token Prefixが異なる場合は、CredentialのTarget nameだけを示して停止します。Token値はエラーへ含めません。

Windows上での初回実行では、起動後に`#adp-control`でテストイベントを送信し、BotがThreadへ応答することを確認します。
