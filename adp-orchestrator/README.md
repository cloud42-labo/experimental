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

`ADP_LOCK_LEASE_SECONDS`はTaskロックの有効期限で、既定値は3600秒です。クラッシュで終了イベントを送れなくても期限切れ後に別Agentが再取得できます。長時間処理では`heartbeat_task`でLeaseを延長できます。

## 起動

```bash
python -m adp_orchestrator.app
```

Slackの`#adp-control`で `@ADP Orchestrator` に続けてJSONイベントを投稿します。実Slackイベントでは、JSON内の`event_id`よりSlack署名済みEnvelopeの`event_id`を優先します。

冪等キーは`correlation_id`、`task_id`、`event_type`、`attempt`を正規化JSONにしてSHA-256化します。そのため、同一試行の重複は排除しつつ、attempt 2・3は別の再試行として処理でき、区切り文字を含むID同士も衝突しません。

Taskロックは`work_started`で取得し、Lock Owner本人の`work_completed`または`failed`だけが解除できます。古いAgentから遅れて届いた終了イベントは現行AgentのロックやNotion状態を変更しません。

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

純粋ロジック・モックHTTPテストは**55件**です。

- 正規化ハッシュによる冪等性とattempt 3までのエスカレーション
- Task Lock Owner検証、期限切れ回収、Heartbeat、旧DB移行
- 古いAgentの終了イベント拒否
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
