# experimental — 実験用リポジトリ

ここは試作・検証を行う場所。本番運用や継続的なメンテナンスは前提にしない。

> このファイルは `GEMINI.md`(`@CLAUDE.md` で本体を読み込む)としても共有している。
> Claude Code と Gemini CLI の両方がここを読む前提で、特定のツールに固有の指示は書かない。

## セッション開始時

作業を始める前に、`cloud42-labo/brain` がまだセッションに無ければ`add_repo`で
追加する。過去の決定・教訓（`decisions/`・`notes/`）が入っており、参照せずに
作業すると同じ失敗を繰り返しやすい。これも`cloud42-labo/brain`に限らず、Claude Code
が関わる全リポジトリに適用する基本ルール（詳細:
[brain/notes/attach-brain-every-session](https://github.com/cloud42-labo/brain/blob/main/notes/attach-brain-every-session.md)）。

## 構成

**1ディレクトリ1プログラム。** ルート直下に、試したもの単位でディレクトリを切る。

```
experimental/
├── todo-app/     # ToDo メモアプリ(HTML/CSS/JS)
└── <new-thing>/  # 新しい試作はここに追加
```

- 言語・フレームワークはディレクトリごとに異なってよい。共通の技術スタックを強制しない
- ルート直下に共通の設定ファイル(package.json など)は置かない。依存関係はディレクトリの中で完結させる
- 1つの試作が終わったら、続きをやるかどうかに関わらずディレクトリごと残す。削除ではなく「触らなくなる」で終わる

## 新しい試作を始めるとき

1. ルート直下に kebab-case のディレクトリを作る(例: `line-bot-poc/`)
2. そのディレクトリの中で完結させる。他のディレクトリのファイルを参照しない
3. 必要なら、そのディレクトリ内に簡単な README を置く(全体の README とは別)

## 記録

このリポジトリ自体には記録を残さない。「何を試したか」「どうなったか」は
[cloud42-labo/brain](https://github.com/cloud42-labo/brain) の `notes/` に書く。
ここはコードだけを置く場所。

## GitHub操作

**このリポジトリは実験・PoC用の例外として、作業エージェント自身によるPRの自己マージを許可する。**
Claudeが作ったPRも、必要な修正、CI、mergeabilityを確認したうえでClaude自身がマージまで進めてよい。
ChatGPT / Chris の再判定や追加承認を必須のマージゲートにしない。

これは本番系・継続運用リポジトリで採用する「実装者とマージ判断を分離する」既定ルールの
**experimental限定の例外**。`experimental`から正式プロダクト用リポジトリへ卒業した後は、
そのリポジトリ側の通常の独立レビュー・マージルールに従う。

## PRレビュー・マージ

1. 作業エージェントがPRを作る
2. Codex Automatic reviews が有効な場合、その指摘を技術的な改善材料として確認する
3. P0/P1、CI失敗、競合など明確なブロッカーがあれば修正する
4. 問題が解消したら、**PR作成者自身がマージしてよい**

- Codexレビューは有用だが、`experimental`ではChatGPT / Chrisの再レビュー待ちを必須条件にしない
- P2以下は試作目的・リスク・後続の実機検証計画を踏まえて、作業エージェントがマージ可否を判断してよい
- 自前のGitHub Actionsワークフロー（`openai/codex-action` / `anthropics/claude-code-action`をAPI課金で呼び出す方式）は課金回避のため使用しない
- 詳細な共通レビュー方針は [brain/notes/ai-pr-review-loop](https://github.com/cloud42-labo/brain/blob/main/notes/ai-pr-review-loop.md) を参照。ただし**自己マージ可否については本ファイルのexperimental例外を優先する**

### マージ後の完了トランザクション

Notion管理下のTaskに対応するPRは、**GitHubでマージしただけでは完了ではない**。マージ担当の作業エージェントが、Notion同期と後続Taskの解放までを同じ完了処理として実行する。

1. **マージ前にNotion接続を確認する。** 対応Taskを取得できず、マージ後のStatus更新を保証できない場合は、Notion管理下のPRをマージしない。
2. PRをマージし、必要なCI / Deploy / Releaseが成功したことを確認する。
3. 対応するStories & Tasksへ `Pull Request` と `Result` を記録する。**Acceptance Criteriaをすべて満たした場合に限り**、`Completed At` を記録し、同じ完了判定の中で `Status = Done` にする。AC未達、Human実機確認待ち、Release待ち等のGateが残る場合は `Completed At` を設定せず、Taskを未完了状態のまま維持する。
4. Task本文に `## AI Handoff` がある場合は、完了更新前に現在のhandoffを再取得する。自分が保持する `workflow_state = active` のhandoffであることをread-before-writeで確認し、TaskをDoneにする同じ完了トランザクション内で `workflow_state = completed` へ更新する。別ownerのactive handoff、更新競合、契約不整合があれば推測更新せず停止する。
5. そのTaskを前提・Blockerにしている後続Taskを再取得して依存関係を再評価する。
6. 他の未完了BlockerがなければBlocker記述を解除し、Definition of Readyを満たす後続Taskを `Ready` に進める。
7. Parent Story / Epicの状態も、子Taskの最新状態に基づいて必要な場合だけ更新する。
8. 最後に再取得して、GitHubのmerge状態、NotionのTask/後続Task、および利用時はAI Handoffの `workflow_state = completed` が一致していることを確認する。

この処理は冪等に行い、再実行しても二重完了・不正なStatus遷移を起こさないこと。対応Taskを特定できない、Acceptance Criteriaの充足が不明、Human実機確認などのGateが残る場合は推測でDoneにしない。**「マージしたので終了」ではなく、「GitHubとNotionの整合確認が通ったので終了」**を終了条件とする。

## バージョニング

試作が育って継続的に使われるようになったアプリには、セマンティックバージョニング
（`MAJOR.MINOR.PATCH`、桁数制限なし）を適用する。これも`cloud42-labo/brain`に
限らず、Claude Codeが関わる全リポジトリ・全アプリに適用する基本ルール
（詳細: [brain/notes/semver-and-release-deliverables](https://github.com/cloud42-labo/brain/blob/main/notes/semver-and-release-deliverables.md)）。

| 桁 | 上げるタイミング | 例 |
| :--- | :--- | :--- |
| MAJOR | 別ゲームレベルの破壊的変更（会計エンジンの全面刷新など） | `0.x.x` → `1.0.0` |
| MINOR | 機能追加・新画面・新指標の追加 | `0.9.x` → `0.10.0` |
| PATCH | バグ修正・文言変更・UIの微調整 | `0.9.6` → `0.9.7` |

- 変更後は各アプリの `index.html` 冒頭の `APP_VERSION` 定数を必ず更新する
- **正式リリースへの昇格**: プロダクトオーナー（駒場さん）が正式リリースを宣言したタイミングで `v1.0.0` に上げる。それまでの `0.x.x` はすべてプレリリース扱い
- **v1.0.0になったら`experimental`から卒業する**: `v1.0.0`昇格は、そのアプリ専用の新規リポジトリ（公開/public）を立てて切り出すトリガーとする。`experimental`は試作・プレリリースまでの場所という前提を維持する（詳細: [brain/notes/semver-and-release-deliverables](https://github.com/cloud42-labo/brain/blob/main/notes/semver-and-release-deliverables.md)）

## リリース時のDeliverables

正式にバージョン管理・リリースするアプリには、開発用ファイルとは別に `deliveries/`
フォルダを切り、その中に**リリースバージョンごとのサブフォルダ**（例:
`deliveries/v0.1.0/`）を作る。各バージョンフォルダには以下をまとめて入れる。

| ファイル | 内容 |
| :--- | :--- |
| はじめてガイド | エンドユーザー向けの導入・使い方ガイド |
| ユーザー向けPRD | 開発者向けの内部PRD/GDDとは別に、ユーザー・ステークホルダー向けに書き直した製品要件文書 |
| プレスリリース（PRFAQ法） | Amazonの"Working Backwards"に倣い、プレスリリース＋FAQ形式で製品価値を説明する文書 |
| アプリ本体（`index.html`等） | そのバージョン時点のスナップショット。以後そのバージョンフォルダの中身は変更しない |

新しいバージョンをリリースするたびに、新しいバージョンフォルダを追加する（過去の
バージョンフォルダは上書きしない）。各ドキュメントのコピーライト表記には
`cloud42-labo` を入れる。
