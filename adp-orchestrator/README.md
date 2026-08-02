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

```bash
cd adp-orchestrator
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

macOS / Linux:

```bash
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

WindowsでTokenを`.env`へ複製せずに起動するLauncherはスタックPR #58で提供します。Windows資格情報マネージャーの汎用資格情報を正本にし、Tokenを子Python Processへだけ渡します。

## 設定

```plain text
ADP_LOCK_LEASE_SECONDS=3600
ADP_RUNTIME_LEASE_SECONDS=60
ADP_RUNTIME_HEARTBEAT_SECONDS=10
```

- `ADP_LOCK_LEASE_SECONDS`: Worker RunのLock Lease
- `ADP_RUNTIME_LEASE_SECONDS`: Orchestrator Process OwnerのLease
- `ADP_RUNTIME_HEARTBEAT_SECONDS`: Process Owner Heartbeat間隔

Runtime HeartbeatはRuntime Leaseの3分の1以下にします。アプリはDaemon Threadと各Slackイベント受付前の両方でOwner Leaseを更新します。

## 起動

```bash
python -m adp_orchestrator.app
```

Slackの`#adp-control`で`@ADP Orchestrator`に続けてJSONイベントを投稿します。実Slackイベントでは、JSON内の`event_id`よりSlack署名済みEnvelopeの`event_id`を優先します。先頭のOrchestrator mentionだけを除去し、`summary`などJSON文字列内のSlack mentionは保持します。

## Runと冪等性

1回の試行は`task_id + correlation_id + attempt`から生成する`run_id`で識別します。同じClaudeでもattempt 1とattempt 2は別Runです。

通常イベントの冪等キーは`run_id + event_type`をcanonical JSON化してSHA-256で生成します。Heartbeatだけは同じRunで繰り返せるよう、Slack署名済み`event_id`も含めます。

Terminalイベントでは、次のOutcome定義をすべて冪等キーへ含めます。

- Source / Target Agent
- event_type / status / summary
- Notion URL / GitHub URL
- requires_human
- attempt / max_attempts

そのため、Slack Envelope IDだけが異なる完全一致の再配信は同じイベントとして扱い、status、summary、max_attemptsなどが変わった再投稿は矛盾する別Outcomeとして拒否します。

## Task LockとTerminal配信予約

Task Lockは`work_started`で取得し、Agent名とRun IDの組合せで所有します。Event ClaimとLock取得は同一SQLite Transactionで行います。競合したStartはClaimを残さず、現行Run終了後に同じイベントを再送できます。

`work_completed`、`failed`、Worker自身の`human_required`は、同じAgent・同じRunだけがTerminal配信を予約できます。最初に受理したTerminal Outcomeを固定し、予約時点ではTask Lockを解放しません。Notion更新とSlack通知がすべて成功した後にだけFinalizeしてLockを解放します。

Terminal配信に失敗した場合は、配信OwnerとEvent Claimだけを戻し、元Run Lockと選択済みOutcomeを保持します。完全一致するTerminalイベントだけを再試行でき、矛盾する完了／失敗は受理しません。

Start側の配信失敗は、Exact Runの非Terminal Lockを実際に削除できた場合だけClaimを戻します。すでにTerminal処理へ進んだRunがStart再配信で復活することを防ぎます。

## Orchestrator Process OwnerとCrash復旧

Terminal予約には、配信を担当するOrchestrator Processの`terminal_owner_id`を保存します。各Processは`runtime_instances`へ期限付きOwner Leaseを登録し、稼働中はHeartbeatを継続します。

- 旧OwnerのLeaseが有効な間、別ProcessはTerminal予約を奪わない
- 旧Ownerが生存中に届いた同一Terminal再配信は`deferred`としてProcess内Queueへ1件だけ保持する
- QueueはRuntime Lease経過後に自動再試行する
- 旧Ownerが先にFinalizeした場合、Deferred処理は安全に終了する
- 旧OwnerのLeaseが失効した場合、同じRun・同じOutcomeだけを新Processへ移譲する
- 異なるTerminal Outcomeへの変更はOwner失効後も拒否する
- 旧Ownerによる遅延Finalize / RollbackはOwner条件で拒否する
- 正常終了ではOwner Leaseを即時解除する

Runtime Heartbeatが失敗したProcessは新しいSlackイベントを受け付けずFail Closedします。

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

最新headでは112 testsが成功しています。

主な検証範囲:

- Run IDと衝突しない冪等性
- Terminal Outcome全項目の固定
- Event ClaimとStart Lock取得の原子性
- Terminal配信予約・Finalize・Rollback・Exact Retry
- Terminal配信完了まで後続Runを開始させない制御
- Start再配信による完了Runの復活防止
- Runtime Ownerの二重配信防止とCrash Recovery
- Active Owner中に届いた再配信のDeferred自動再試行
- Worker / Runtime Heartbeat
- 古いattempt、誤Agent、stale Human Requestの拒否
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
├── router.py
├── runtime.py
└── service.py
```

## 制約

- PC停止中はイベントを処理しません
- Deferred QueueはProcess内に保持します。新Process自体も再度停止した場合はSlackイベントの再投稿が必要です
- Slackの過去メッセージ再同期は未実装です
- Notion実接続にはTokenとページ共有権限が必要です
- GitHub Adapterは現在読み取り専用です
- AI起動Adapterは現在No-opです
- 常時稼働環境への移行はAI Handoff E2E成功後に判断します
