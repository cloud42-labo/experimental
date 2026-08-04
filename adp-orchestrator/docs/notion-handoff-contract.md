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
| 実施済み内容 | `Result` | **単独では不十分。** Notion Adapterが自動更新で上書きする（下記「`Result`の扱い」） |
| 未解決P0・P1 | — | **表せない**（`Blocker`は停止理由用で、意味が違う） |
| エラーまたは停止理由 | `Blocker` | 足りる（ただしAdapterが上書きしうる） |
| 次に実行すべき具体的な一手 | — | **表せない** |

### プロパティを追加しない理由

表せない項目のために`Stories & Tasks`へプロパティを追加することはしない。

- Mission ControlのAuto集計（`Task Count Auto` / `Done Count Auto` / `Progress Auto %`）と
  Relation/Rollup構成（ADP-007）に影響が及ぶ。引継ぎのためだけにその構成をいじるのは割に合わない。
- 「未解決P0/P1」「次の一手」は自由記述であり、select/urlのような構造化の恩恵が小さい。
- 増やすより減らす方向で構成を保つ（[brain/CLAUDE.md](https://github.com/cloud42-labo/brain/blob/main/CLAUDE.md)の週次レビュー方針）。

代わりに、**本文末尾の`## AI Handoff`ブロック1つ**で残りをまとめて持つ。1回のページ取得で
現在地が一望でき、再開に必要な情報がプロパティと本文へ散らばらない。

### `Result`の扱い — Adapterが上書きする

`NOTION_TOKEN`が設定されOrchestratorのNotion Adapterが有効な場合、通常イベントのたびに
`Result`はその時点の`RouteResult.message`だけで**置換**される（`src/adp_orchestrator/notion_adapter.py`の
`NotionTaskRepository.record`。`Blocker`も同様）。したがって`Result`へ経緯を積み上げても、
次の自動遷移で消える。

**`Result`は「最新の一言」を持つ揮発フィールドとして扱い、再開時に信頼する情報源にしない。**
消えて困る経緯は次のいずれかへ残す。

- **`## AI Handoff`ブロック（本文）** — Adapterはページの`properties`しか更新せず、本文ブロックには触らない。
  引継ぎの正本はこちら。
- **PR本文・PRコメント・コミットメッセージ** — 役割間の受け渡しの記録（[claude-role-separation.md](claude-role-separation.md)）。
- **[brain](https://github.com/cloud42-labo/brain)** — 恒久的な決定・教訓。

## 本文テンプレート（`## AI Handoff`ブロック）

各タスクページの**末尾**に置き、工程が変わるたびに**このブロックごと上書きする**（追記しない）。

```yaml
## AI Handoff

updated_at: <ISO-8601のUTCタイムスタンプ。秒まで書く。例 2026-08-04T07:20:31Z>
updated_by: <claude-pm | claude-implementer | claude-reviewer | claude-fixer | chatgpt-backup | human>
current_role: <pm | implementer | reviewer | fixer | none>
workflow_id: <実行を識別する値。Slack起動ならthread_ts、直接起動ならセッションid。claude-role-separation.mdと同じ>
attempt: <この受入条件に対する実行回数。1から。claude-role-separation.mdのattempt lifecycleに従う>
commits:
  - <コミットURLまたはSHA。無ければ空リスト []>
open_p0_p1: <未解決のP0/P1。無ければ空リスト []。フィールド自体の省略は禁止>
next_action: <次に実行する具体的な一手。「レビュー待ち」で終えず、誰が何をするかまで書く>
requires_human: <true | false。trueなら理由をBlockerにも書く>
```

`Status`・`Acceptance Criteria`・`GitHub Issue`・`Pull Request`は**プロパティ側が正**とし、
このブロックには複製しない（二重管理を避ける）。`Result`・`Blocker`はAdapterが上書きしうるため、
再開時に必要な内容はこのブロック側にも持つ。

### 同一タスクに対する並行workflow

[claude-role-separation.md](claude-role-separation.md)は同一`task_id`に対して複数の`workflow_id`が
存在しうることを許容する（attempt履歴を区別するため）。一方、Notionページの`## AI Handoff`ブロックは
1タスクに1つしかない。そのまま上書きを許すと、先行するworkflowの現在地を古い状態で潰しうる。

**原則: 同一`task_id`に対して同時にactiveなworkflowは1つとする。** 引継ぎがNotionページ1つに
集約される以上、並行実行は引継ぎとして表現できない。

上書き前に、**必ず既存ブロックを読んでから書く**（read-before-write）。

**判定は`current_role`で行う。`updated_at`の新旧では判定しない。**
`updated_at`が古いことは「終了した」ことの証明にならない（単に長時間Notionを更新していない
だけの、稼働中のworkflowかもしれない）。一方`current_role`は、PMが役割の受け渡し・完了のたびに
明示的に更新する値であり、「今まさに誰かがこのタスクの役割についているか」を表す。

| 既存ブロックの状態 | 対応 |
|---|---|
| ブロックが無い | 新規に書いてよい |
| `workflow_id`が自分と同じ | そのまま上書きしてよい（自分自身の継続） |
| `workflow_id`が自分と異なり、`current_role`が`none` | 先行workflowは役割から離れている（完了・一時停止のいずれか）。上書きしてよい |
| `workflow_id`が自分と異なり、`current_role`が`none`以外（`pm`/`implementer`/`reviewer`/`fixer`） | 別のworkflowが役割中＝稼働中とみなす。**上書きしない。** `requires_human: true`として停止し、どちらを継続するかオーナーへ確認する |

**フェイルクローズを意図した設計。** workflowが役割の途中でクラッシュし`current_role`を
`none`へ戻せなかった場合、そのタスクは後続workflowから見て「稼働中」のまま残り、以後は
人間の確認待ちで止まる。これは意図した挙動である。「本当は終わっているのに稼働中に見える」ために
毎回人間の手を煩わせるコストより、「稼働中のworkflowを気づかず上書きする」事故を防ぐことを優先する。
クラッシュを検知して回復したPM（別workflowまたは人間）が、状況を確認した上で`current_role: none`へ
書き戻して解除する。

`updated_at`は秒精度のUTCタイムスタンプのまま残すが、役割は「監査用の最終更新時刻」に限定する
（安全性の判定には使わない）。

## 記入規則

- **更新するのはPMの責務**（[claude-role-separation.md](claude-role-separation.md)の「他の役割はNotionを直接更新しない」と一致）。
  Implementer/Reviewer/FixerはPR本文へ引継ぎを残し、Notionへの反映はPMが行う。
- **`next_action`を空欄・「レビュー待ち」だけで終えない。** 再開する側が最初の一手を判断できなければ
  引継ぎとして機能しない。「Chrisのマージを待つ。マージされたらStatusをDoneにし、HUMAN-xx-1へ実機確認を依頼する」まで書く。
- **`open_p0_p1`のフィールド自体を省略しない。** 未解決が無いときは空リスト`[]`と書く。
  フィールドが無ければ「まだ確認していない」と解釈する。
- **PRを作った時点で必ず1回更新する。** PR作成からマージまでの間が、他エージェントが引き継ぐ可能性の最も高い区間。
- **書く前に既存ブロックを読む。** 上表のworkflow競合判定を行う。

## 再開手順（Claude / ChatGPT 共通）

引き継ぐ側は、このタスクページだけを起点に次の順で復元する。

1. `Title`からTask IDと対象を、本文冒頭から目的を読む。
2. `Acceptance Criteria`で「何をもって完了か」を確認する。
3. `Status`と`## AI Handoff`の`current_role`で現在工程を特定する。
4. `## AI Handoff`で実施済みの経緯と現在地を読む。`Result`・`Blocker`は
   Adapterに上書きされている可能性があるため、補助的な情報として扱う。
5. `GitHub Issue` / `Pull Request` / `commits`で成果物の実体を確認する。
   **記録と実体が食い違う場合は実体を正とし、記録を直してから進む**（記録は数時間で陳腐化する）。
6. `open_p0_p1`が空リストでなければ、そこに挙がっている指摘を片付けることを最優先にする。
   空リストなら次へ進む。フィールドが無い場合は「未確認」とみなし、PR上のレビュー状態を自分で確認する。
7. `next_action`を実行する。`requires_human: true`なら、実行せずオーナーへ確認する。

ChatGPTがバックアップとして入る場合も手順は同じ。Claude固有の前提（Claude Codeのセッション、
サブエージェント）に依存する情報は`next_action`へ書かず、**成果物とNotion/GitHubの状態だけで
判断できる形**にする。

## 記入例

```yaml
## AI Handoff

updated_at: 2026-08-04T07:20:31Z
updated_by: claude-pm
current_role: none
workflow_id: session_01HvemhQPLFL33FBFF6GYUf5
attempt: 1
commits:
  - https://github.com/cloud42-labo/experimental/commit/0432626
open_p0_p1: []
next_action: Chrisのマージを待つ。マージされたらStatusをDoneへ更新し、実機確認が必要な変更のためHUMAN-06-1へ確認を依頼する。
requires_human: false
```

## 関連

- [claude-role-separation.md](claude-role-separation.md) — 役割間1回の受け渡し（PR本文に残す）
- [slack-native-loop-spec.md](slack-native-loop-spec.md) — Slack上のメッセージcontract
- [CLAUDE.md](../../CLAUDE.md)
- [brain/notes/notion-vibe-product-development](https://github.com/cloud42-labo/brain/blob/main/notes/notion-vibe-product-development.md)
