# ADP Orchestrator MVP

SlackをAI同士の自由会話に使うのではなく、タスク、結果、レビュー、Human Requestを受け渡すイベントバスとして使うローカルMVPです。

## 方針

- Slack Appは1つだけ使う
- Socket Modeで受信し、公開HTTPエンドポイントを不要にする
- 外部AI APIは呼ばない。追加課金を発生させない
- Notionは計画・進捗、GitHubはコード・PR、Slackは会話・通知・起動の正本とする
- Tokenや秘密情報をログ・Git・Slack本文へ出さない
- タスクイベントは`#adp-control`だけで受け付ける

## 必要環境

- Python 3.12以上
- Slack Bot Token (`xoxb-...`)
- Slack App-Level Token (`xapp-...`、`connections:write`)
- Notion更新を有効にする場合だけNotion Integration Token
- private GitHubリポジトリを参照する場合だけGitHub Token

## セットアップ

### Windows PowerShell

```powershell
cd adp-orchestrator
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

実Tokenは`.env`やPowerShell履歴へ貼り付けず、Windows資格情報マネージャーの**汎用資格情報**を正本にします。

| Target name | Password |
|---|---|
| `ADP_SLACK_BOT_TOKEN` | `xoxb-...` |
| `ADP_SLACK_APP_TOKEN` | `xapp-...` |

登録方法と起動方法の詳細は[`scripts/README.md`](scripts/README.md)を参照してください。

### macOS / Linux

```bash
cd adp-orchestrator
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

`.env`を使う場合もGit管理せず、権限を限定してください。`NOTION_TOKEN`と`GITHUB_TOKEN`は空欄でも起動できます。

`ADP_LOCK_LEASE_SECONDS`はTaskロックの有効期限で、既定値は3600秒です。クラッシュで終了イベントを送れなくても期限切れ後に別Runが再取得できます。長時間処理では`work_heartbeat`イベントを定期送信し、同一Agent・同一RunだけがLeaseを延長できます。

## 起動

### Windows

```powershell
.\scripts\start-windows.ps1 `
  -ControlChannelId C0123456789 `
  -HumanRequestsChannelId C0123456790 `
  -DailyChannelId C0123456791 `
  -PythonCommand .\.venv\Scripts\python.exe
```

Windows Launcherは資格情報マネージャーからTokenを読み、子Python Processの環境変数だけへ渡します。成功すると`Bolt app is running!`と表示されます。

### macOS / Linux

```bash
python -m adp_orchestrator.app
```

Slackの`#adp-control`で `@ADP Orchestrator` に続けてJSONイベントを投稿します。実Slackイベントでは、JSON内の`event_id`よりSlack署名済みEnvelopeの`event_id`を優先します。

### Runと冪等性

1回の試行は`task_id + correlation_id + attempt`から生成する`run_id`で識別します。同じClaudeでもattempt 1とattempt 2は別Runです。

イベントの冪等キーは`run_id + event_type`を正規化JSONにしてSHA-256化します。Heartbeatだけは同じRunで繰り返すため、Slack署名済み`event_id`も含めます。これにより、同一Heartbeatの再配信は排除しつつ、次のHeartbeatは受理できます。

### Task LockとTerminal配信予約

Taskロックは`work_started`で取得し、Agent名とRun IDの組合せで所有します。Event ClaimとLock取得は同一SQLite Transactionで実行するため、競合したStartはClaimを残さず、現行Run終了後に同じイベントを再送できます。

`work_completed`、`failed`、Worker自身の`human_required`は、同じAgent・同じRunだけがTerminal配信を予約できます。予約時点ではLockを解放しません。Notion更新とSlack通知がすべて成功した後にだけLockを確定解放するため、配信途中に後続Runが開始することはありません。

Terminal配信に失敗した場合は、Terminal予約とEvent Claimだけを原子的に戻し、元のRun Lockは保持します。同じTerminalイベントを再送して配信をやり直せます。Start側の配信失敗は、Exact Runの非Terminal Lockを実際に削除できた場合だけClaimを戻すため、すでにTerminal処理へ進んだRunがStart再配信で復活することを防ぎます。

古いattemptから遅れて届いた完了・失敗・Human Requestや、異なるAgentからのイベントはConflictとして拒否し、現行RunのロックやNotion状態を変更しません。

### Heartbeat

長時間処理では次のイベントを定期送信します。

```json
{
  "schema_version": "1.0",
  "event_id": "Slack側で上書きされる",
  "task_id": "ADP-012-D",
  "correlation_id": "同じRunの相関ID",
  "from_agent": "claude",
  "to_agent": "chris",
  "event_type": "work_heartbeat",
  "status": "running",
  "summary": "実装を継続中",
  "attempt": 1,
  "max_attempts": 3
}
```

Heartbeatは非Terminal状態のExact RunだけがLeaseを延長でき、NotionやAI起動Adapterへ副作用を出しません。

## Adapter構造

- `TaskRepository`: Notionなどへタスク状態を記録
- `AgentActivator`: 次のAI作業をキューへ渡す
- `GitHubReferenceClient`: Issue / Pull Requestを読み取る
- 既定値は安全なNo-op Adapter

`NOTION_TOKEN`設定時だけ`NotionTaskRepository`が有効になり、`Status`、`Result`、`Assigned Agent`、`Blocker`、`Environment Help`を更新します。Codexも正式なAssigned Agentとして扱います。HTTPエラーとDNS・接続・Timeoutなどのtransport errorは、Tokenやレスポンス本文を含まない安全なエラーへ変換し、元例外のContextも抑止します。

Notion更新、AI起動、Slack返信・Human Request通知が一時失敗した場合は、イベント種別に応じた安全なrollbackを行います。Slack再送または再投稿で処理を継続できます。

`GitHubReferenceClient`は読み取り専用です。公開Issue / PRはTokenなし、privateリポジトリは`GITHUB_TOKEN`付きで参照できます。

## テスト

```bash
pytest
```

純粋ロジックとMockTransportによる回帰テストで、次を確認します。

- attempt単位のRun IDと衝突しない冪等性
- Event ClaimとStart Lock取得の原子性
- Terminal配信予約・成功時Finalize・失敗時Retry
- Terminal配信完了まで後続Runを開始させない制御
- Start再配信による完了Runの復活防止
- 同一Runで繰り返せるHeartbeat
- Agent + Run IDによるTask Lock所有権
- 期限切れ回収、Heartbeat、旧DB移行
- 同じAgentの古いattempt終了イベント拒否
- stale Human Requestの拒否
- Human Request対象の自動起動禁止
- Notion Status / Result / Blockerの設定と解除
- Codex担当のNotion反映
- Notion / GitHub transport errorの安全な正規化と秘密情報非露出
- GitHub Issue / PR URL解析とメタデータ取得

2026-08-02にWindows実機で、資格情報読取、Socket Mode接続、`app_mention`受信、正式な`task_assigned`イベントの`accepted`返信まで確認済みです。

## ディレクトリ

```text
src/adp_orchestrator/
├── adapters.py
├── app.py
├── config.py
├── events.py
├── github_adapter.py
├── idempotency.py
├── notion_adapter.py
├── router.py
└── service.py
```

## 制約

- PC停止中はイベントを処理しません
- Slackの過去メッセージ再同期は未実装です
- Notion実接続にはTokenとページ共有権限が必要です
- GitHub Adapterは現在読み取り専用です
- Windows Launcherの実Slack E2Eは確認済みですが、常時稼働環境ではありません
- 常時稼働環境への移行は追加機能のE2E成功後に判断します
