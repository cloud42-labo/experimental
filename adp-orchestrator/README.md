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
Copy-Item .env.example .env
```

### macOS / Linux

```bash
cd adp-orchestrator
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

`.env`へTokenとチャンネルIDを設定します。`.env`はGit管理しません。`NOTION_TOKEN`と`GITHUB_TOKEN`は空欄でも起動できます。

`ADP_LOCK_LEASE_SECONDS`はTaskロックの有効期限で、既定値は3600秒です。クラッシュで終了イベントを送れなくても期限切れ後に別Runが再取得できます。長時間処理では`work_heartbeat`イベントを定期送信し、同一Agent・同一RunだけがLeaseを延長できます。

## 起動

```bash
python -m adp_orchestrator.app
```

Slackの`#adp-control`で `@ADP Orchestrator` に続けてJSONイベントを投稿します。実Slackイベントでは、JSON内の`event_id`よりSlack署名済みEnvelopeの`event_id`を優先します。

### Runと冪等性

1回の試行は`task_id + correlation_id + attempt`から生成する`run_id`で識別します。同じClaudeでもattempt 1とattempt 2は別Runです。

イベントの冪等キーは`run_id + event_type`を正規化JSONにしてSHA-256化します。Heartbeatだけは同じRunで繰り返すため、Slack署名済み`event_id`も含めます。これにより、同一Heartbeatの再配信は排除しつつ、次のHeartbeatは受理できます。

### Task Lock

Taskロックは`work_started`で取得し、Agent名とRun IDの組合せで所有します。`work_completed`、`failed`、Worker自身の`human_required`は、同じAgent・同じRunだけが解除できます。

古いattemptから遅れて届いた完了・失敗・Human RequestはConflictとして拒否し、現行RunのロックやNotion状態を変更しません。`work_started`が競合した場合はevent claimを戻すため、現行Run終了後に同じStartイベントを再送できます。

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

HeartbeatはローカルLeaseだけを更新し、NotionやAI起動Adapterへ副作用を出しません。

## Adapter構造

- `TaskRepository`: Notionなどへタスク状態を記録
- `AgentActivator`: 次のAI作業をキューへ渡す
- `GitHubReferenceClient`: Issue / Pull Requestを読み取る
- 既定値は安全なNo-op Adapter

`NOTION_TOKEN`設定時だけ`NotionTaskRepository`が有効になり、`Status`、`Result`、`Assigned Agent`、`Blocker`、`Environment Help`を更新します。Codexも正式なAssigned Agentとして扱います。HTTPエラーとDNS・接続・Timeoutなどのtransport errorは、Tokenやレスポンス本文を含まない安全なエラーへ変換します。

Notion更新、AI起動、Slack返信・Human Request通知が一時失敗した場合はevent claimを戻し、必要なTaskロックも解除または復元します。Slack再送または再投稿で処理を継続できます。

`GitHubReferenceClient`は読み取り専用です。公開Issue / PRはTokenなし、privateリポジトリは`GITHUB_TOKEN`付きで参照できます。

## テスト

```bash
pytest
```

純粋ロジック・モックHTTPテストは**64件**です。

- attempt単位のRun IDと衝突しない冪等性
- 同一Runで繰り返せるHeartbeat
- Agent + Run IDによるTask Lock所有権
- 期限切れ回収、Heartbeat、旧DB移行
- 同じAgentの古いattempt終了イベント拒否
- stale Human Requestの拒否
- Start競合後の同一イベント再試行
- 外部Adapter・Slack送信失敗後のRollback
- Human Request対象の自動起動禁止
- Notion Status / Result / Blockerの設定と解除
- Codex担当のNotion反映
- Notion transport errorの安全な正規化
- GitHub Issue / PR URL解析とメタデータ取得
- Notion / GitHub HTTPエラー時の秘密情報非露出

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
- 実Slack E2EはWorkspaceとToken準備後に行います
- 常時稼働環境への移行はE2E成功後に判断します
