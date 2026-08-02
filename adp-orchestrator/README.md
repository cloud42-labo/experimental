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
  "notion_url": "https://app.notion.com/p/<task-page-id>",
  "github_url": "https://github.com/cloud42-labo/experimental/pull/57",
  "requires_human": false,
  "attempt": 1,
  "max_attempts": 3
}
```

実Slackイベントでは、JSON内の`event_id`よりSlack署名済みEnvelopeの`event_id`を優先します。`attempt`は冪等キーに含まれるため、同じ`correlation_id`でもattempt 2・3を別の再試行として処理できます。

Taskロックは`work_started`で取得し、`work_completed`または`failed`を送信したAgent本人だけが解除できます。古いAgentから遅れて届いた完了・失敗イベントは現行AgentのロックやNotion状態を変更しません。

## Adapter構造

外部連携は本体から分離しています。

- `TaskRepository`: Notionなどへタスク状態を記録する境界
- `AgentActivator`: 次のAI作業をキューへ渡す境界
- `GitHubReferenceClient`: Issue / Pull Requestを読み取る境界
- MVP既定値は`NoopTaskRepository`と`NoopAgentActivator`

`NOTION_TOKEN`が未設定ならTask更新はNo-opです。設定されている場合だけ`NotionTaskRepository`が自動的に有効になり、`Status`、`Result`、`Assigned Agent`、`Blocker`、`Environment Help`を更新します。

Notion更新、AI起動、Slack返信・Human Request通知が一時失敗した場合はevent claimを戻します。`work_started`の失敗時は取得したロックも解除し、完了・失敗イベントの配信失敗時は元のWorkerロックを可能な範囲で復元します。これによりSlack再送または再投稿で処理を継続できます。

`GitHubReferenceClient`は読み取り専用です。公開Issue / PRはTokenなし、privateリポジトリは`GITHUB_TOKEN`付きで参照できます。MVPではGitHubへの書き込みは行いません。

## テスト

```bash
pytest
```

現在の純粋ロジック・モックHTTPテストは45件です。

- イベント契約の検証
- attemptを含む冪等キーとattempt 3までのエスカレーション
- Slack Envelope event IDの優先
- 原子的な重複イベント排除
- `task_assigned`から`work_started`への正常遷移
- 同一Taskの二重Running防止
- Lock Owner一致による完了・失敗時の解除
- 古いAgentの完了・失敗イベントの拒否
- 失敗時のロック解放と再試行
- 外部Adapter・Slack送信失敗後のevent claimロールバック
- 3回失敗後のHuman Request化
- Human Request対象の自動起動禁止
- Tokenを例外へ含めない設定検証
- Notion Token有無によるNo-op / 実Adapter切替
- Notion Update pageのリクエスト形式
- Notion Status / Result / Blockerの設定と解除
- GitHub Issue / PR URL解析とメタデータ取得
- Notion / GitHub HTTPエラー時の秘密情報非露出

## ディレクトリ

```text
src/adp_orchestrator/
├── adapters.py       # Notion・AI起動の境界と安全なNo-op
├── app.py            # Slack Socket Modeの入口と送信失敗Rollback
├── config.py         # 環境変数検証と任意Token
├── events.py         # メッセージ契約とattempt単位の冪等キー
├── github_adapter.py # GitHub Issue / PR読み取りAdapter
├── idempotency.py    # SQLite処理履歴とOwner付きTaskロック
├── notion_adapter.py # Notion Page更新Adapter
├── router.py         # 状態遷移、Owner検証、Rollback
└── service.py        # RouterとAdapterの調停
```

## 制約

- PC停止中はイベントを処理しません
- Slackの過去メッセージ再同期は未実装です
- Notion Adapterの実接続にはTokenとページ共有権限が必要です
- GitHub Adapterは現在読み取り専用です
- 実Slack SDK接続はWorkspaceとToken準備後にE2E確認します
- 本番運用や常時稼働環境への移行は、E2E成功後に判断します
