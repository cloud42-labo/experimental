# ADP Orchestrator MVP

SlackをAI同士の自由会話に使うのではなく、タスク、結果、レビュー、Human Requestを受け渡すイベントバスとして使うローカルMVPです。

## 方針

- Slack Appは1つだけ使う
- Socket Modeで受信し、公開HTTPエンドポイントを不要にする
- 外部AI APIは呼ばない。追加課金を発生させない
- Notionは計画・進捗、GitHubはコード・PR、Slackは会話・通知・起動の正本とする
- Tokenや秘密情報をログ・Git・Slack本文へ出さない

## 必要環境

- Python 3.12以上
- Slack AppのBot Token (`xoxb-...`)
- Slack App-Level Token (`xapp-...`、`connections:write`)

## セットアップ

```bash
cd adp-orchestrator
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
```

`.env`へTokenとチャンネルIDを設定します。`.env`はGit管理しません。

## 起動

```bash
python -m adp_orchestrator.app
```

Slackで `@ADP Orchestrator` に続けて、次のJSONを投稿します。

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

MVPでは、検証結果と次工程を同じSlackスレッドへ返信します。AI APIの自動起動、Notion更新、GitHub更新はAdapterの実装ポイントとして分離しています。

## テスト

```bash
pytest
```

テスト対象:

- イベント契約の検証
- 重複イベントの排除
- 同一Taskの二重Running防止
- 3回失敗後のHuman Request化
- Tokenを例外へ含めない設定検証

## ディレクトリ

```text
src/adp_orchestrator/
├── app.py           # Slack Socket Modeの入口
├── config.py        # 環境変数検証
├── events.py        # メッセージ契約
├── idempotency.py   # SQLite処理履歴
└── router.py        # 状態遷移とルーティング
```

## 制約

- PC停止中はイベントを処理しません
- Slackの過去メッセージ再同期は未実装です
- Notion/GitHubへの書き込みAdapterは後続実装です
- 本番運用や常時稼働環境への移行は、E2E成功後に判断します
