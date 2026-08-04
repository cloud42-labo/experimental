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

| Target name | User name | Password |
|---|---|---|
| `ADP_SLACK_BOT_TOKEN` | `SLACK_BOT_TOKEN` | `xoxb-...` |
| `ADP_SLACK_APP_TOKEN` | `SLACK_APP_TOKEN` | `xapp-...` |

登録方法と起動方法の詳細は[`scripts/README.md`](scripts/README.md)を参照してください。Signing SecretはSocket Mode起動には使用しません。

### macOS / Linux

```bash
cd adp-orchestrator
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

`.env`を使う場合もGit管理せず、権限を限定してください。`NOTION_TOKEN`と`GITHUB_TOKEN`は空欄でも起動できます。

## 設定

```plain text
ADP_LOCK_LEASE_SECONDS=3600
ADP_RUNTIME_LEASE_SECONDS=60
ADP_RUNTIME_HEARTBEAT_SECONDS=10
```

- `ADP_LOCK_LEASE_SECONDS`: Worker RunのLock Lease
- `ADP_RUNTIME_LEASE_SECONDS`: Orchestrator Process OwnerのLease
- `ADP_RUNTIME_HEARTBEAT_SECONDS`: Process Owner Heartbeat間隔

Runtime HeartbeatはRuntime Leaseより短く設定します。アプリはDaemon Threadと各Slackイベント受付前の両方でOwner Leaseを更新します。

## 起動

### Windows

```powershell
.\scripts\start-windows.ps1 `
  -ControlChannelId C0123456789 `
  -HumanRequestsChannelId C0123456790 `
  -DailyChannelId C0123456791 `
  -PythonCommand .\.venv\Scripts\python.exe
```

Windows Launcherは資格情報マネージャーからTokenを読み、子Python Processの環境変数だけへ渡します。Tokenを`.env`、コマンドライン引数、標準出力、Gitへ書きません。成功すると`Bolt app is running!`と表示されます。

### macOS / Linux

```bash
python -m adp_orchestrator.app
```

Slackの`#adp-control`で`@ADP Orchestrator`に続けてJSONイベントを投稿します。実Slackイベントでは、JSON内の`event_id`よりSlack署名済みEnvelopeの`event_id`を優先します。先頭のOrchestrator mentionだけを除去し、`summary`などJSON文字列内のSlack mentionは保持します。

## ACKと永続Outbox

Slack Boltは`process_before_response=True`で構築し、Listener完了前の早期ACKを防ぎます。

Validation済みイベントは、Routing、Notion更新、Agent起動、Slack返信より前にSQLiteの`deferred_deliveries` Outboxへ保存します。

- 直接Listener処理が成功した場合だけOutbox行を削除する
- Adapter、Slack、Finalizeが失敗した場合はOutbox行を残して自動再試行する
- 同一semantic keyは1行へ集約する
- 直接処理中は参照カウントでSchedulerによる同一イベント処理を抑止する
- Duplicate / Conflict返信の成功はOwner処理の完了証明にしない
- Process再起動時は保存済みOutboxを自動再開する
- Routing ClaimがCrash前に保存済みでも、Outbox行が残る限り外部配信未完了として再構成する

Claim済みの`task_assigned`、`review_requested`、`work_started`は、保存済みEventと現行Lockから受理結果を復元します。`work_started`に後続Terminal予約が存在する場合、古い`running`状態をNotionへ戻さず、欠けたSlack側だけを補完します。

## Runと冪等性

1回の試行は`task_id + correlation_id + attempt`から生成する`run_id`で識別します。同じClaudeでもattempt 1とattempt 2は別Runです。

通常イベントの冪等キーは`run_id + event_type`をcanonical JSON化してSHA-256で生成します。Heartbeatだけは同じRunで繰り返せるよう、Slack署名済み`event_id`も含めます。

Terminalイベントでは、次のOutcome定義をすべて冪等キーへ含めます。

- Source / Target Agent
- event_type / status / summary
- Notion URL / GitHub URL
- requires_human
- attempt / max_attempts

Slack Envelope IDだけが異なる完全一致の再配信は同じOutcomeとして扱い、status、summary、max_attemptsなどが変わった再投稿は矛盾する別Outcomeとして拒否します。

## Task LockとTerminal配信予約

Task Lockは`work_started`で取得し、Agent名とRun IDの組合せで所有します。Event ClaimとLock取得は同一SQLite Transactionで行います。競合したStartはClaimを残さず、現行Run終了後に同じイベントを再送できます。

`work_completed`、`failed`、Worker自身の`human_required`は、同じAgent・同じRunだけがTerminal配信を予約できます。最初に受理したTerminal Outcomeを固定し、予約時点ではTask Lockを解放しません。Notion更新とSlack通知がすべて成功した後にだけFinalizeしてLockを解放します。

Terminal配信に失敗した場合は、配信OwnerとEvent Claimだけを戻し、元Run Lockと選択済みOutcomeを保持します。完全一致するTerminalイベントだけを再試行でき、矛盾する完了／失敗は受理しません。

Start側の配信失敗は、Exact Runの非Terminal Lockを実際に削除できた場合だけClaimを戻します。すでにTerminal処理へ進んだRunがStart再配信で復活することを防ぎます。

## Orchestrator Process OwnerとCrash復旧

Terminal予約には配信を担当するOrchestrator Processの`terminal_owner_id`を保存します。各Processは`runtime_instances`へ期限付きOwner Leaseを登録し、稼働中はHeartbeatを継続します。

ローカルMVPではSQLite DBごとのOS Process File Lockも取得し、同じDBを使うOrchestratorの二重起動を拒否します。Windowsでは`msvcrt.locking`、Unixでは`fcntl.flock`を使用します。

- 旧OwnerのLeaseが有効な間、別ProcessはTerminal予約を奪わない
- 旧Ownerが生存中に届いた再配信はSQLite Outboxへ保持する
- 旧Ownerが先にFinalizeした場合、Outbox側は安全に終了する
- 旧OwnerのLease失効後は同じRun・同じOutcomeだけを新Processへ移譲する
- 異なるTerminal Outcomeへの変更はOwner失効後も拒否する
- Notion、Agent起動、Slack、Human Request、Finalize直前にDelivery Guardを実行する
- 旧Ownerによる遅延Finalize / RollbackはOwner条件で拒否する
- 正常終了ではOwner LeaseとOS Process Lockを解放する

Runtime Heartbeatが失敗したProcessは新しいSlackイベントや外部副作用を受け付けずFail Closedします。

## Worker Heartbeat

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

Worker Heartbeatは非Terminal状態のExact RunだけがTask Lock Leaseを延長でき、NotionやAI起動Adapterへ副作用を出しません。Orchestrator Process Owner Heartbeatとは別の仕組みです。

## イベント契約の制約

- `work_started`のTargetはClaude / Gemini / Codexのみ
- `work_started`は`requires_human=true`を許可しない
- `work_heartbeat`、`work_completed`、`failed`のSourceはWorker Agentのみ
- WorkerのHuman Requestは`human_required`イベントを使う
- `to_agent=human`は自動的に`requires_human=true`となる

## Adapter構造

- `TaskRepository`: Notionなどへタスク状態を記録
- `AgentActivator`: 次のAI作業をキューへ渡す
- `GitHubReferenceClient`: Issue / Pull Requestを読み取る
- 既定値は安全なNo-op Adapter

`NOTION_TOKEN`設定時だけ`NotionTaskRepository`が有効になり、`Status`、`Result`、`Assigned Agent`、`Blocker`、`Environment Help`を更新します。Codexも正式なAssigned Agentとして扱います。

Notion / GitHubのHTTP・DNS・接続・Timeoutエラーは、Tokenやレスポンス本文を含まない安全なAdapter Errorへ正規化し、元例外のContextも抑止します。

## テスト

```bash
pytest -q
```

GitHub Actionsは、`adp-orchestrator/**`のPull Requestと対象Branch Pushで次を自動実行します。

- Python 3.12
- Package / Dev dependenciesの導入
- `python -m compileall -q src`
- Full Test Suite

最新headでは132 testsが成功しています。

Windows実機では2026-08-02に、資格情報読取、Socket Mode接続、`app_mention`受信、正式な`task_assigned`イベントの`accepted`返信まで確認しました。

主な検証範囲:

- Run IDと衝突しない冪等性
- Terminal Outcome全項目の固定
- Event ClaimとStart Lock取得の原子性
- ACK前のOutbox永続化
- 直接処理中のOutbox競合防止
- Routing Claim保存後のCrash復旧
- Process再起動後のOutbox再開
- Terminal配信予約・Finalize・Rollback・Exact Retry
- Terminal配信完了まで後続Runを開始させない制御
- OS Process LockとRuntime Owner Fence
- Worker / Runtime Heartbeat
- 古いattempt、誤Agent、stale Human Requestの拒否
- Windows Credential API、Secret経路、`.env`非生成、秘密値非表示
- Notion / GitHub transport errorの秘密情報非露出

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
├── outbox.py
├── router.py
├── runtime.py
└── service.py

docs/
├── slack-native-loop-spec.md      # Slack上のAgent間ループ／グラフ仕様
├── claude-role-separation.md      # Claude PM/Implementer/Reviewer/Fixerの役割定義
└── notion-handoff-contract.md     # Notionへ残す引継ぎの記入契約
```

## 制約

- PC停止中はイベントを処理しません
- SQLite Outboxは同じDBを使用する次回起動時に再開します
- Slackの過去メッセージ再同期は未実装です
- Notion実接続にはTokenとページ共有権限が必要です
- GitHub Adapterは現在読み取り専用です
- AI起動Adapterは現在No-opです
- Windows Launcherの実Slack E2Eは確認済みですが、常時稼働環境ではありません
- 常時稼働環境への移行はAI Handoff E2E成功後に判断します
