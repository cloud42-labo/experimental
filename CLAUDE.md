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

**2026-08-26、オーナー判断でこのリポジトリは自己マージに切り替えた。**
`experimental`はデモ・試作環境であり、レビューの厳密さよりまず動かすことを優先するため、
「Claudeが作ったPR（`claude/*`ブランチ）は作ったところで止め、Claude自身はマージしない」
という従来のルール（全リポジトリ共通の例外ルール
[brain/notes/ai-pr-review-loop](https://github.com/cloud42-labo/brain/blob/main/notes/ai-pr-review-loop.md)）を、
**このリポジトリに限って**さらに上書きし、本来の既定ルール
（[brain/notes/github-pr-workflow](https://github.com/cloud42-labo/brain/blob/main/notes/github-pr-workflow.md)、
PRを作ったら止めずマージまで行う）に戻す。経緯:
[brain/decisions/0021](https://github.com/cloud42-labo/brain/blob/main/decisions/0021-oek-t06-merge-authority-conflict.md)・
[brain/decisions/0022](https://github.com/cloud42-labo/brain/blob/main/decisions/0022-experimental-self-merge-exception.md)。

## PRレビュー・マージ

1. Claude が `claude/*` ブランチでPRを作る
2. **Codex の Automatic reviews**（ChatGPT Plus/Pro契約の範囲）による自動レビューは
   引き続き有効にしておく。レビュー規約は [AGENTS.md](AGENTS.md) の `## Code Review Rules`。
   品質シグナルとして無料で得られるので、指摘が既に付いていれば直してから進める
3. CIが green で、その時点までに付いているCodex指摘に対応していれば、
   **Claude自身がその場でsquashマージする。** ChatGPT側の毎時タスクによるマージ実行を
   待たない（待っても実害は無いが、速度を優先しない理由が無い）
4. 判断に迷う指摘（設計レベルの大きな指摘など）は、他リポジトリと同じ通常の
   PRドライブ方針に従う。デモ環境なので「まず動かす」を優先してよい

- 自前のGitHub Actionsワークフロー（`openai/codex-action` / `anthropics/claude-code-action`
  をAPI課金で呼び出す方式）は一度実装したが、課金を避けるためにやめた。詳細は
  [brain/decisions/0008 の追記](https://github.com/cloud42-labo/brain/blob/main/decisions/0008-ai-review-loop-codex-vs-claude.md)
- **これはこのリポジトリ固有の例外。** 他のリポジトリ（`serendipity-spot`など）は
  従来どおりChatGPT側マージ委任のまま変更していない
- 詳細: [brain/notes/ai-pr-review-loop](https://github.com/cloud42-labo/brain/blob/main/notes/ai-pr-review-loop.md)・
  [brain/decisions/0022](https://github.com/cloud42-labo/brain/blob/main/decisions/0022-experimental-self-merge-exception.md)

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
- **正式リリースへの昇格**: プロダクトオーナー（駒場さん）が正式リリースを宣言した
  タイミングで `v1.0.0` に上げる。それまでの `0.x.x` はすべてプレリリース扱い
- **v1.0.0になったら`experimental`から卒業する**: `v1.0.0`昇格は、そのアプリ専用の
  新規リポジトリ（公開/public）を立てて切り出すトリガーとする。`experimental`は
  試作・プレリリースまでの場所という前提を維持する（詳細:
  [brain/notes/semver-and-release-deliverables](https://github.com/cloud42-labo/brain/blob/main/notes/semver-and-release-deliverables.md)）

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
