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
- Slack AppのBot Token (`xoxb-...`)
- Slack App-Level Token (`xapp-...`、`connections:write`)

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

`.env`へTokenとチャンネルIDを設定します。`.env`はGit管理しません。

## 起動

```bash
python -m adp_orchestrator.app
```

Slackの`#adp-control`で `@ADP Orchestrator` に続けて、次のJSONを投稿します。

```json
{
  "schema_version": "1.0",
  "event_id": "example-event-1",
  "task_id": "ADP-012",
  "correlation_id": "example-correlation-1",
  "from_agent": "chris",
  "to_agent": "claude",
  "event_type": "task_assigned",
  "status": "ready",
  "summary": "Orchestrator MVPを実装する",
  "requires_human": false,
  "attempt": 1,
  "max_attempts": 3
}
```

実Slackイベントでは、JSON内の`event_id`よりSlack署名済みEnvelopeの`event_id`を優先します。MVPは検証結果と次工程を同じSlackスレッドへ返信します。

## Adapter構造

外部連携は本体から分離しています。

- `TaskRepository`: Notionなどへタスク状態を記録する境界
- `AgentActivator`: 次のAI作業をキューへ渡す境界
- MVP既定値は`NoopTaskRepository`と`NoopAgentActivator`

このため、実Tokenがない状態でもルーティングをテストでき、有料AI APIを無断で呼びません。

## テスト

```bash
pytest
```

現在の純粋ロジックテストは23件です。

- イベント契約の検証
- Slack Envelope event IDの優先
- 原子的な重複イベント排除
- `task_assigned`から`work_started`への正常遷移
- 同一Taskの二重Running防止
- 失敗時のロック解放と再試行
- 3回失敗後のHuman Request化
- Human Request対象の自動起動禁止
- Tokenを例外へ含めない設定検証
- Adapterの副作用境界

## ディレクトリ

```text
src/adp_orchestrator/
├── adapters.py      # Notion・AI起動の境界と安全なNo-op
├── app.py           # Slack Socket Modeの入口
├── config.py        # 環境変数検証
├── events.py        # メッセージ契約
├── idempotency.py   # SQLite処理履歴とTaskロック
├── router.py        # 状態遷移とルーティング
└── service.py       # RouterとAdapterの調停
```

## 制約

- PC停止中はイベントを処理しません
- Slackの過去メッセージ再同期は未実装です
- Notion/GitHubへの実書き込みAdapterは後続実装です
- 実Slack SDK接続はWorkspaceとToken準備後にE2E確認します
- 本番運用や常時稼働環境への移行は、E2E成功後に判断します
