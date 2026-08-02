# Windows起動Script

`start-windows.ps1`は、Windows資格情報マネージャーに保存したSlack Tokenを読み取り、ADP Orchestratorの子Python Processへだけ渡します。

## 前提

資格情報マネージャーで「Windows 資格情報」を開き、下段の**汎用資格情報**として次の2件を登録します。上段の通常のWindows資格情報では読み取れません。

| Target name | User name | Passwordに保存する値 |
|---|---|---|
| `ADP_SLACK_BOT_TOKEN` | `SLACK_BOT_TOKEN` | Slack Bot Token（`xoxb-`で始まる値） |
| `ADP_SLACK_APP_TOKEN` | `SLACK_APP_TOKEN` | Slack App-Level Token（`xapp-`で始まる値） |

TokenをPowerShellへ貼り付けたり、`.env`へ複製したりしません。Signing SecretはSocket Mode起動には使用しません。

## 起動

仮想環境を有効化し、`adp-orchestrator`ディレクトリで次を実行します。

```powershell
.\scripts\start-windows.ps1 `
  -ControlChannelId C0123456789 `
  -HumanRequestsChannelId C0123456790 `
  -DailyChannelId C0123456791 `
  -PythonCommand .\.venv\Scripts\python.exe
```

3つの値には、それぞれ次のSlack Channel IDを指定します。

- `#adp-control`
- `#adp-human-requests`
- `#adp-daily`

Channel IDは秘密情報ではありません。チャンネル名ではなく、`C`または`G`で始まるIDを指定します。

起動に成功すると、PowerShellへ次が表示され、Processは待機状態になります。

```text
Bolt app is running!
```

PowerShellを閉じるか子Processを終了すると、ローカルOrchestratorも停止します。

## Secretの扱い

ScriptはTokenを次へ書き込みません。

- `.env`
- コマンドライン引数
- 標準出力
- Git

TokenはLauncher Processのローカル変数と、子Python Processの環境変数にだけ存在します。子Process終了後、Launcher側の参照と`ProcessStartInfo`内のTokenを削除します。

## エラー

資格情報が存在しない、Passwordが空、Token Prefixが異なる場合は、CredentialのTarget nameだけを示して停止します。Token値はエラーへ含めません。

`could not be read`となる場合は、同名の資格情報が上段のWindows資格情報ではなく、下段の**汎用資格情報**に登録されているか確認します。

## Windows実機Smoke Test

2026-08-02に次の実機確認を完了しました。

- Windows PowerShell
- Python 3.13.14
- 仮想環境作成と`pip install -e ".[dev]"`成功
- Full Test Suite: `pytest -q` 100%成功
- 汎用資格情報から`xoxb-` / `xapp-` Tokenを読取
- Launcher出力: `Bolt app is running!`
- Slack Socket Modeで`app_mention`を受信
- `hello`投稿に対して期待どおりValidation Errorを返信
- 正式な`task_assigned` JSONイベントを受理
- Threadへ`Result: accepted`、`Status: ready`、`Target: claude`を返信

このSmoke Testでは、Token値を画面、ログ、Git、Slack本文へ出していません。
