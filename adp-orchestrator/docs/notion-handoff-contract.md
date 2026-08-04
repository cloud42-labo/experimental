# Notion AI引継ぎ契約

## Status

ADP-019-B。Notionの`Stories & Tasks`を、**ClaudeとChatGPTのどちらでも、そのページだけを読んで
作業を再開できる状態**に保つための記入契約を定める。

[claude-role-separation.md](claude-role-separation.md)（ADP-019-A）が定めるのは**役割間1回の受け渡し**で、
PR本文に残す。本ドキュメントが定めるのは**タスクの現在地のスナップショット**で、Notionページを上書き更新する。
両者は語彙を共有するが、寿命が違う（前者は追記して残る、後者は常に最新1件）。

## 必須引継ぎ項目と既存プロパティの対応

`Stories & Tasks`の既存プロパティで表現できる項目は、**新しいプロパティを足さずに既存を使う**。

| 必須引継ぎ項目 | Notionでの表現 | 十分か |
|---|---|---|
| Task IDと目的 | `Title`（`ADP-019-B｜...`のようにID前置） + 本文冒頭 | ID: 足りる。目的は本文に書く |
| 現在工程 | `Status`（Backlog / Ready / In Progress / Review / Done / Blocked） | **粗い。** 役割（PM/Implementer/Reviewer/Fixer）のどこにいるかは表せない |
| 受入条件 | `Acceptance Criteria` | 足りる |
| 対象リポジトリ・Issue・PR | `GitHub Issue`、`Pull Request`（URLにリポジトリが含まれる） | 足りる |
| 対象コミット | — | **表せない** |
| 実施済み内容 | `Result` | 足りる |
| 未解決P0・P1 | — | **表せない**（`Blocker`は停止理由用で、意味が違う） |
| エラーまたは停止理由 | `Blocker` | 足りる |
| 次に実行すべき具体的な一手 | — | **表せない** |

### プロパティを追加しない理由

表せない4項目のために`Stories & Tasks`へプロパティを追加することはしない。

- Mission ControlのAuto集計（`Task Count Auto` / `Done Count Auto` / `Progress Auto %`）と
  Relation/Rollup構成（ADP-007）に影響が及ぶ。引継ぎのためだけにその構成をいじるのは割に合わない。
- 「未解決P0/P1」「次の一手」は自由記述であり、select/urlのような構造化の恩恵が小さい。
- 増やすより減らす方向で構成を保つ（[brain/CLAUDE.md](https://github.com/cloud42-labo/brain/blob/main/CLAUDE.md)の週次レビュー方針）。

代わりに、**本文末尾の`## AI Handoff`ブロック1つ**で4項目をまとめて持つ。1回のページ取得で
現在地が一望でき、再開に必要な情報がプロパティと本文へ散らばらない。

## 本文テンプレート（`## AI Handoff`ブロック）

各タスクページの**末尾**に置き、工程が変わるたびに**このブロックごと上書きする**（追記しない）。

```yaml
## AI Handoff

updated_at: <YYYY-MM-DD、更新した日>
updated_by: <claude-pm | claude-implementer | claude-reviewer | claude-fixer | chatgpt-backup | human>
current_role: <pm | implementer | reviewer | fixer | none>
workflow_id: <実行を識別する値。Slack起動ならthread_ts、直接起動ならセッションid。claude-role-separation.mdと同じ>
attempt: <この受入条件に対する実行回数。1から。claude-role-separation.mdのattempt lifecycleに従う>
commits:
  - <コミットURLまたはSHA。無ければ空>
open_p0_p1:
  - <未解決のP0/P1。無ければ「なし」と明記する>
next_action: <次に実行する具体的な一手。「レビュー待ち」で終えず、誰が何をするかまで書く>
requires_human: <true | false。trueなら理由をBlockerにも書く>
```

`Status`・`Acceptance Criteria`・`Result`・`Blocker`・`GitHub Issue`・`Pull Request`は
**プロパティ側が正**とし、このブロックには複製しない（二重管理を避ける）。

## 記入規則

- **更新するのはPMの責務**（[claude-role-separation.md](claude-role-separation.md)の「他の役割はNotionを直接更新しない」と一致）。
  Implementer/Reviewer/FixerはPR本文へ引継ぎを残し、Notionへの反映はPMが行う。
- **`next_action`を空欄・「レビュー待ち」だけで終えない。** 再開する側が最初の一手を判断できなければ
  引継ぎとして機能しない。「Chrisのマージを待つ。マージされたらStatusをDoneにし、HUMAN-xx-1へ実機確認を依頼する」まで書く。
- **`open_p0_p1`は「なし」を省略しない。** 空欄は「未解決が無い」のか「確認していない」のか区別できない。
- **PRを作った時点で必ず1回更新する。** PR作成からマージまでの間が、他エージェントが引き継ぐ可能性の最も高い区間。
- **`Result`は経緯を残す（追記）、`AI Handoff`は現在地を示す（上書き）。** 役割が違うので両方書く。

## 再開手順（Claude / ChatGPT 共通）

引き継ぐ側は、このタスクページだけを起点に次の順で復元する。

1. `Title`からTask IDと対象を、本文冒頭から目的を読む。
2. `Acceptance Criteria`で「何をもって完了か」を確認する。
3. `Status`と`## AI Handoff`の`current_role`で現在工程を特定する。
4. `Result`で実施済み内容を、`Blocker`で停止理由を読む。
5. `GitHub Issue` / `Pull Request` / `commits`で成果物の実体を確認する。
   **記録と実体が食い違う場合は実体を正とし、記録を直してから進む**（記録は数時間で陳腐化する）。
6. `open_p0_p1`が空でなければ、それを片付けることを最優先にする。
7. `next_action`を実行する。`requires_human: true`なら、実行せずオーナーへ確認する。

ChatGPTがバックアップとして入る場合も手順は同じ。Claude固有の前提（Claude Codeのセッション、
サブエージェント）に依存する情報は`next_action`へ書かず、**成果物とNotion/GitHubの状態だけで
判断できる形**にする。

## 記入例

```yaml
## AI Handoff

updated_at: 2026-08-04
updated_by: claude-pm
current_role: none
workflow_id: session_01HvemhQPLFL33FBFF6GYUf5
attempt: 1
commits:
  - https://github.com/cloud42-labo/experimental/commit/0432626
open_p0_p1:
  - なし（Codexレビュー4件はすべて対応・スレッド解決済み）
next_action: Chrisのマージを待つ。マージされたらStatusをDoneへ更新し、実機確認が必要な変更のためHUMAN-06-1へ確認を依頼する。
requires_human: false
```

## 関連

- [claude-role-separation.md](claude-role-separation.md) — 役割間1回の受け渡し（PR本文に残す）
- [slack-native-loop-spec.md](slack-native-loop-spec.md) — Slack上のメッセージcontract
- [CLAUDE.md](../../CLAUDE.md)
- [brain/notes/notion-vibe-product-development](https://github.com/cloud42-labo/brain/blob/main/notes/notion-vibe-product-development.md)
