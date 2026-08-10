# experimental

試作・検証用リポジトリ。ルート直下に、試したもの単位でディレクトリを切る
（**1ディレクトリ1プログラム**）。本番運用や継続的なメンテナンスは前提にしない。

運用ルールは [CLAUDE.md](CLAUDE.md) を参照。

## 構成

```
experimental/
├── human-capital-portfolio-management/ # 人財ポートフォリオマネジメント研修ゲーム試作
├── serendipity-spot/           # 「ついでにスポット」HTML試作（v1.0.0はcloud42-labo/serendipity-spotへ移管済み）
├── serendipity-spot-android/   # 同アプリのネイティブAndroid版
├── store-survival-simulator/   # 店舗生存シミュレーター
├── todo-app/                   # ToDoメモアプリ
└── <new-thing>/                # 新しい試作はここに追加
```

## 開発運用

このリポジトリは [Claude Code](https://claude.com/claude-code) が開発・保守する。
運用ルールは [CLAUDE.md](CLAUDE.md)、AIレビュー規約は [AGENTS.md](AGENTS.md) を参照。

### PRレビュー・マージ

このリポジトリ自体のGitHub Actionsではなく、**ChatGPT側の2つの仕組み**でPRのレビュー・
マージを行う（API課金の発生する自前のワークフローは廃止した。経緯は
[cloud42-labo/brain の decisions/0008 追記](https://github.com/cloud42-labo/brain/blob/main/decisions/0008-ai-review-loop-codex-vs-claude.md) 参照）。

1. Claude が `claude/*` ブランチでPRを作り、**そこで止める（自分ではマージしない）**
2. **Codex の Automatic reviews**（ChatGPT Plus/Pro契約の範囲）が、このリポジトリの
   PRを自動レビューする。レビュー規約は [AGENTS.md](AGENTS.md) の `## Code Review Rules`
   （Codexが自動で読む）。重大度の高い指摘（P0/P1）のみをGitHubの通常のレビューとして投稿する
3. **ChatGPT側の毎時タスク**が、Codexのレビュー結果とCIの状態を確認し、指摘が無く
   CIも問題なければGitHub連携でsquashマージする。指摘があればマージせず待つ

このリポジトリ側で必要な設定は無い（Secretsの登録もWorkflow permissionsの変更も不要）。
ChatGPT側の設定（このリポジトリへのCodex Automatic reviewsの有効化、毎時タスクのGitHub
連携）は別途ChatGPTのCodex設定画面で行う。
