# experimental

試作・検証用リポジトリ。ルート直下に、試したもの単位でディレクトリを切る
（**1ディレクトリ1プログラム**）。本番運用や継続的なメンテナンスは前提にしない。

運用ルールは [CLAUDE.md](CLAUDE.md) を参照。

## 構成

```
experimental/
├── serendipity-spot/           # 「ついでにスポット」HTML試作（v1.0.0はcloud42-labo/serendipity-spotへ移管済み）
├── serendipity-spot-android/   # 同アプリのネイティブAndroid版
├── store-survival-simulator/   # 店舗生存シミュレーター
├── todo-app/                   # ToDoメモアプリ
└── <new-thing>/                # 新しい試作はここに追加
```

## 開発運用

このリポジトリは [Claude Code](https://claude.com/claude-code) が開発・保守する。
運用ルールは [CLAUDE.md](CLAUDE.md)、AIレビュー規約は [AGENTS.md](AGENTS.md) を参照。

### AIレビュー・修正ループ

Claude が作った PR（`claude/*` ブランチ）は、`.github/workflows/ai-pr-review-loop.yml` に
より自動で以下を行う。

1. **OpenAI Codex** が PR の差分をレビューする（レビュー規約は [AGENTS.md](AGENTS.md)）
2. 指摘があれば **Claude** が自動で修正し、コミットをpushする
3. Codex が再レビューする（1〜2を繰り返す）
4. CIが成功し、Codexの指摘が無くなれば**自動でsquashマージ**する
5. **最大3ラウンドで収束しなければ**、`needs-human` ラベルを付けてPRにコメントし、
   それ以上の自動処理を止める（人間の判断待ち）

設計の背景・別ベンダーAIにレビューさせる理由は
[cloud42-labo/brain の decisions/0008](https://github.com/cloud42-labo/brain/blob/main/decisions/0008-ai-review-loop-codex-vs-claude.md) 参照。

**現状の制約:** PR時点で走るCI（テスト・ビルド）は、このリポジトリのどのアプリにも
まだ無い（唯一のCIである `serendipity-spot-android` のビルドworkflowは `main` への push
時のみ動作する）。そのため当面「CI成功」の判定は形骸化し、実質Codexレビューの承認のみが
マージ条件になる。将来いずれかのアプリにPR時点のCIを追加すれば、このワークフローは
変更なしで自動的にそれもゲートに含める。

#### 必要なGitHub Secrets（Settings > Secrets and variables > Actions）

| Secret | 用途 |
| :--- | :--- |
| `ANTHROPIC_API_KEY` または `CLAUDE_CODE_OAUTH_TOKEN` | どちらか一方。Claude Codeによる自動修正 |
| `OPENAI_API_KEY` | Codexによる自動レビュー |

（`serendipity-spot-android` のビルド・署名に使う `SERENDIPITY_*` シークレットとは別物）

#### 必要なリポジトリ設定

- **Settings > Actions > General > Workflow permissions** を
  **`Read and write permissions`** にする（コミットのpush・PRのマージ・ラベル付けに必要）
- （推奨・任意）**Settings > Branches** で `main` にブランチ保護を設定し、直接pushを
  技術的にも禁止する。現状は運用ルール（`CLAUDE.md`）のみで、技術的な強制はされていない

#### 手動での再開・停止

- `needs-human` ラベルが付いたPRは自動処理が止まっている。対応後、ラベルを外し、
  Actions画面から「AI PR Review Loop」を **workflow_dispatch**（PR番号を指定）で
  手動実行するとループを再開できる
- ループ自体を止めたい場合は、`.github/workflows/ai-pr-review-loop.yml` を無効化するか、
  対象PRに手動で `needs-human` ラベルを付ける
