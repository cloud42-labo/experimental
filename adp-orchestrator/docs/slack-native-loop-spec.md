# Slack-native AI Agent Loop / Graph Specification

## Status

Draft for ADP-012-G / ADP-017. This specification replaces the local resident Orchestrator as the primary MVP direction.

## Objective

Use a single Slack thread as the shared execution context for multiple AI agents.

The owner starts work by mentioning Chris. Chris interprets the goal, chooses the next agent, evaluates returned evidence, and continues until a stop condition is reached.

```text
Owner -> @Chris -> @Claude/@Gemini/@Codex -> @Chris -> next action or stop
```

## Principles

1. Slack is the instruction, handoff, result, and notification bus.
2. Notion is the source of truth for plans, decisions, status, and next work.
3. GitHub is the source of truth for code, specifications, PRs, reviews, and releases.
4. One Slack thread represents one workflow.
5. Chris alone decides the next agent and whether the workflow is complete.
6. Native Slack agents are preferred. A local runner, Google Cloud runtime, or external AI API is not introduced unless native Bot-to-Bot triggering fails.
7. Slack messages do not replace required Notion state. Chris must persist the initial plan, material state transitions, blockers, Human Requests, and terminal outcome in Notion.

## Roles

### Owner

- Defines purpose, priority, constraints, permissions, and final business decisions.
- Is contacted only when a Human Request stop condition is reached.

### Chris / Orchestrator Agent

- Receives the owner's initial mention.
- Reads relevant Notion and GitHub state.
- Converts the goal into tasks and acceptance criteria.
- Persists the plan and material workflow state in Notion.
- Selects the next agent.
- Evaluates returned evidence.
- Issues correction, review, merge, next-stage, completion, or Human Request instructions.
- Prevents duplicate or unproductive loops.

### Claude

- Design, implementation, correction, quality checks, and merge work as assigned.

### Gemini

- Ideation, comparison, early specification, UI exploration, and alternative review.

### Codex

- Pull request review and evidence-based defect reporting.

## Workflow identity

- `workflow_id`: Slack `thread_ts`.
- `task_id`: Stable task identifier from Notion or GitHub when available.
- A new top-level Slack message creates a new workflow.
- All subsequent handoffs and results stay in the same thread.

## Minimum message contract

Each agent handoff or result should contain:

```yaml
workflow_id: <thread_ts>
task_id: <stable task id>
from_agent: <owner|chris|claude|gemini|codex>
to_agent: <agent or none>
status: <planned|working|review|blocked|failed|done|human_required|completed|failed_limit|loop_detected|cancelled|capability_failure|turn_limit>
summary: <short description>
result_links:
  - <Notion/GitHub/other evidence URL>
attempt: <integer starting at 1>
next_action: <explicit next action>
requires_human: <true|false>
```

A terminal Slack message (see "Stop conditions") maps each of the seven stop tags directly onto a `status` value, with no inference needed: `COMPLETED` → `completed`, `FAILED_LIMIT` → `failed_limit`, `LOOP_DETECTED` → `loop_detected`, `CANCELLED` → `cancelled`, `CAPABILITY_FAILURE` → `capability_failure`, `TURN_LIMIT` → `turn_limit`, and `HUMAN_REQUEST` → the existing `human_required` value already in the enum above (no separate `human_request` value is added, since `human_required` already covers it).

Natural-language Slack messages may be used, but these fields must be inferable and should be included explicitly for multi-turn work.

## Attempt lifecycle

`attempt` counts unsuccessful execution attempts for the same `workflow_id + task_id + acceptance scope`, independent of which agent is assigned. There is exactly one attempt counter per task; it is not tracked separately per agent.

1. The first dispatch of the task, to any agent, starts at `attempt: 1`.
2. `planned`, `working`, and progress updates for that dispatch retain the same attempt number.
3. Slack delivery retries, duplicate event delivery, reconnects, and transport failures do not increment the attempt.
4. An attempt is unsuccessful when any of the following (this list is exhaustive — no other event increments `attempt`):
   - the assigned agent returns `failed`; or
   - the assigned agent returns `done` or `review`, but Chris rejects the evidence because the stated acceptance criteria are not met; or
   - the assigned agent returns `blocked` and Chris determines the blocker cannot be resolved, closing that dispatch as rejected.
5. When Chris redispatches the same task after an unsuccessful attempt, the attempt increments by one, regardless of whether the redispatch goes to the same agent or a different agent. Reassigning to a different agent does not reset or start a separate counter.
6. A `blocked` result does not by itself make the current attempt unsuccessful, because "blocked" alone is not one of the three predicates in rule 4. When Chris resolves the blocker, the resumed dispatch keeps the same attempt number that was active when the block occurred — it is not a new dispatch of the next attempt, and nothing increments. Only when Chris cannot resolve the blocker and closes the dispatch as rejected (third predicate in rule 4) does the current attempt become unsuccessful; that closure marks the current attempt number itself as unsuccessful (per rule 5's counting). If that was the task's third unsuccessful attempt, rule 8 takes precedence and Chris stops with `FAILED_LIMIT`, not `HUMAN_REQUEST`/`CAPABILITY_FAILURE`; on the first or second unsuccessful attempt, Chris stops with `HUMAN_REQUEST` or `CAPABILITY_FAILURE` instead of redispatching to a new attempt number.
7. `human_required` stops the workflow immediately and does not consume another attempt.
8. After three unsuccessful attempts on the task, regardless of agent mix, Chris must stop with `FAILED_LIMIT`; a fourth execution attempt on that task is not permitted without the owner explicitly changing the goal or acceptance scope.
9. A material change to the goal or acceptance scope creates a new task or workflow rather than resetting the counter silently.
10. For parallel dispatch (see Graph patterns → Parallel and merge), each branch must use a distinct `task_id` (for example `<task_id>-claude`, `<task_id>-gemini`) so branch outcomes never share one counter and a branch's own attempt lifecycle follows rules 1-8 independently. The parent task has its own separate attempt counter, with its own execution boundary: a parent attempt begins when Chris issues the parallel dispatch and ends when Chris evaluates the synthesized merge against acceptance criteria — that evaluation, not any individual branch result, is the parent's execution outcome for rule 4. Rejecting the synthesized merge is therefore equivalent to a rejected `done`/`review` under rule 4 and increments the parent's counter; an individual branch failing, by itself, does not. Rule 8 applies to the parent counter exactly as it does to any task: if the merge just rejected was the parent's third unsuccessful attempt (`attempt: 3`), Chris stops the parent task with `FAILED_LIMIT` immediately and does not redispatch any branch or re-run synthesis — no further increment happens, matching rule 8's "no fourth execution attempt." Otherwise (the rejected merge was attempt 1 or 2), the parent's counter increments by one per rule 5, and Chris redispatches only the branches whose evidence was rejected, giving each a fresh attempt under the same branch `task_id` (rules 1-8 apply per branch as normal); branches whose evidence was already accepted are not redispatched, and their accepted evidence carries forward unchanged into the next merge evaluation. If every branch's evidence was individually accepted and it is the synthesis itself that fails acceptance criteria, there is no branch to redispatch; the next parent attempt is a re-synthesis, where Chris either re-evaluates the same accepted branch evidence against clarified acceptance criteria, or explicitly requests supplemental evidence from one or more already-accepted branches because the rejected synthesis specifically requires it — either path is the parent's execution for that attempt and produces the next merge evaluation, again subject to the same three-attempt limit on the parent counter. A supplemental request to an already-accepted branch is dispatched under a new branch `task_id` (for example `<task_id>-claude-2`, distinct from the original `<task_id>-claude`), starting its own attempt lifecycle at `attempt: 1` under rules 1-8; it never reuses or increments the original branch's counter, since the original dispatch's evidence was already accepted and remains a separate, closed execution. The branch-only exception is limited to `FAILED_LIMIT`: a branch reaching its own failure limit stops dispatch to that branch only, not the whole parallel task — unless that branch is required for the merge condition and can no longer satisfy it, in which case Chris stops the parent task too, propagating `FAILED_LIMIT` rather than choosing a different status independently. A branch returning `HUMAN_REQUEST` or `CAPABILITY_FAILURE` is not branch-scoped: per rule 7 and Stop conditions 2 and 6, either one stops the whole workflow immediately, regardless of whether that branch was required for the merge — the other branches' in-flight dispatches are abandoned rather than awaited.

## Notion persistence requirements

Chris must keep Notion synchronized at these control points:

1. Before the first agent dispatch: create or update the task with the goal, acceptance criteria, plan, assigned agent, and `In Progress` status.
2. At each material transition: record assignment changes, accepted evidence, rejected evidence, blockers, correction requests, and Human Requests.
3. Before posting a terminal Slack message: persist the terminal status, result summary, evidence links, unresolved items, and next human action when applicable.
4. If the terminal Notion write fails for any reason — unreachable, timed out, rejected for permissions, or rejected for validation — do not declare `COMPLETED`, and do not let the failed write block the owner-facing stop message. Rule 5 defines the fallback that applies in every one of these cases.
5. **Persistence-failure exception.** Whenever the terminal Notion write does not succeed, persistence-before-notification (rule 3) is waived for that one post so the workflow still has a valid stop path:
   - Chris posts the terminal Slack message anyway, labeled `persisted_to_notion: false` and naming the failure kind (`notion_unavailable`, `notion_permission_denied`, `notion_validation_rejected`, or similar);
   - the status used is `CAPABILITY_FAILURE` for unreachable/timeout failures, and `HUMAN_REQUEST` for permission or validation failures, since those need the owner (or Notion schema/access owner) to act before a write can ever succeed;
   - the message includes everything that would normally go to Notion (goal, evidence links, unresolved items, next human action), since the Notion record does not yet exist;
   - native Slack agents have no independent timer or background process, so this specification does not rely on unattended automatic retry; the terminal message must explicitly ask the owner to re-mention Chris in the same thread once the underlying cause is resolved (Notion reachable again, access restored, or schema/payload fixed) — that mention is the only retry trigger;
   - when that re-mention arrives, Chris backfills the terminal record in Notion synchronously before confirming the task closed, then posts confirmation in the thread;
   - this exception only ever changes when persistence happens (after, instead of before, the terminal message, and driven by an explicit re-mention rather than a timer); it never allows Chris to skip persisting altogether once the write can succeed.

## Standard loop

1. Owner mentions Chris with a goal.
2. Chris defines acceptance criteria and a plan, persists them in Notion, and summarizes them in the same Slack thread.
3. Chris mentions one or more next agents.
4. Each agent performs work and returns evidence in the same thread while mentioning Chris.
5. Chris evaluates the evidence against the acceptance criteria and records the material result or transition in Notion.
6. Chris chooses one action:
   - assign the next task;
   - request correction with the next attempt number;
   - request review;
   - approve completion;
   - create a Human Request;
   - stop due to loop protection.
7. Before any terminal Slack message, Chris writes the final status and evidence to Notion, except under the persistence-failure exception defined in "Notion persistence requirements".
8. Repeat until stopped.

## Graph patterns

### Sequential

```text
Chris -> Claude -> Chris -> Codex -> Chris -> Claude -> Chris -> Done
```

### Parallel and merge

```text
                 -> Claude --\
Chris -> dispatch -> Gemini ----> Chris synthesizes -> next action
                 -> Codex  --/
```

Chris must state the expected responses and the merge condition before parallel dispatch. Each branch dispatched in parallel uses a distinct `task_id` per the attempt lifecycle (rule 10), so branch-level failures and the parent's merge-level attempt counter never share one number.

### Correction loop

```text
Chris -> Claude attempt 1 -> Chris rejects evidence
      -> Claude attempt 2 -> Chris accepts evidence -> Done
```

## Stop conditions

A workflow stops when any condition is true:

1. Acceptance criteria are satisfied, evidence is recorded, and the terminal state is persisted in Notion.
2. Human judgment, credentials, permissions, billing, or physical-device work is required.
3. The same task reaches three unsuccessful attempts as defined in the attempt lifecycle. For a task dispatched under a distinct branch `task_id` inside a parallel dispatch (rule 10), this condition stops that branch's own dispatch only, per rule 10 — it stops the whole workflow only when it is the parent task's own counter (not a branch's) that reaches three, or when a branch's exhaustion means the merge condition can no longer be satisfied at all, per rule 10's closing clause.
4. The workflow reaches twenty agent turns. A turn is counted each time Chris or an agent posts a non-terminal message carrying the minimum message contract — a dispatch, an evidence result, or a Chris evaluation/instruction — to the workflow thread; owner messages, Slack delivery retries or duplicate deliveries (attempt-lifecycle rule 3), non-contract natural-language chatter, and the terminal Slack message itself (whichever stop tag it carries) do not count. The count is cumulative across the whole workflow, including the parent and every parallel branch (rule 10), and is not reset by attempt increments. Once 19 non-terminal turns have been counted, dispatches and other message types are handled differently, because Chris fully controls whether a dispatch is sent but cannot pre-empt a result an agent is already returning from a dispatch sent earlier: Chris checks the count before sending any dispatch, and if it is already at 19, does not send it — a dispatch never becomes turn 20, and Chris stops immediately with `TURN_LIMIT` instead of dispatching. A non-dispatch message — an evidence result from a branch already in flight, or Chris's own evaluation of it — may still land as turn 20 if it is simply the next event in the thread; that message is counted as turn 20, and Chris's only next action is to stop with `TURN_LIMIT` immediately afterward, issuing no further dispatch or evaluation. Either path keeps a dispatch from ever being sent at or after turn 20. The `TURN_LIMIT` stop message itself is excluded from the budget like any terminal message, so it is never turn 21.
5. The same instruction-result pair is repeated twice without new evidence.
6. Required access or capability is unavailable.
7. The owner explicitly stops or changes the goal.

When stopped, Chris posts one of:

- `COMPLETED`
- `HUMAN_REQUEST`
- `FAILED_LIMIT`
- `LOOP_DETECTED`
- `CANCELLED`
- `CAPABILITY_FAILURE` — required access, permissions, or a dependency (including Notion itself, per the persistence-failure exception above) is unavailable and blocks continuation.
- `TURN_LIMIT` — the workflow reached twenty turns as defined in stop condition 4, without another stop condition applying first.

The final message must include achieved results, unresolved items, evidence links, the persisted Notion task link, and the next human action when applicable. Under the persistence-failure exception, the Notion task link is replaced by the full state inline in Slack, since no link exists yet.

**Post-terminal messages.** A workflow enters the stopping state the instant any stop condition is met — for example, the moment turn 20 is counted, or the moment Chris determines a Human Request, failure limit, or capability failure applies — not only once the terminal Slack message has actually been posted; persisting to Notion and posting the terminal message both happen after entry into this state, and that window is not instantaneous. From the moment a workflow enters the stopping state, any other message that arrives — including results and mentions from other branches Chris dispatched before the stop, whether they arrive before or after the terminal Slack post — is not counted toward any turn or attempt total, and Chris does not act on it, evaluate it, or treat an agent's mention in it as reactivating the workflow. If such a message needs a durable record, Chris may note it as an addendum when backfilling Notion (see the persistence-failure exception), but it never produces a new dispatch, a new terminal message, or a resumed workflow.

## Duplicate and loop detection

A message fingerprint is derived from:

```text
workflow_id + task_id + from_agent + to_agent + normalized summary + attempt
```

Chris must not reissue an instruction when the same fingerprint already has a terminal result. If the same instruction and materially identical result recur twice, stop with `LOOP_DETECTED`.

## Native-agent feasibility E2E

### Test A: Human to Chris

- Owner mentions Chris in `#adp-control`.
- Chris replies in the same thread.
- Chris creates or updates the corresponding Notion task before dispatching work.

### Test B: Chris to Claude

- Chris mentions Claude in the thread.
- Claude starts without a new human message.

### Test C: Claude to Chris

- Claude returns a result and mentions Chris.
- Chris resumes without a new human message.
- Chris records the result or next transition in Notion.

### Test D: Correction loop

- Chris rejects the first result and records it as unsuccessful `attempt: 1`.
- Chris requests one correction as `attempt: 2`.
- Claude returns the correction.
- Chris persists the accepted result and closes the workflow.

### Test E: Stop control

All four scenarios below are independently mandatory — each must be run and pass on its own; passing only some does not satisfy Test E.

- **Test E1 — Human Request:** trigger a Human Request. Confirm the terminal status is persisted in Notion before the final Slack post, and that the workflow stops and does not self-restart.
- **Test E2 — Loop detection:** repeat the same instruction-result pair twice without new evidence. Confirm Chris detects it and stops with `LOOP_DETECTED`, persisted in Notion before the final Slack post, without self-restarting.
- **Test E3 — Failure limit:** using a non-branch (top-level or parent) `task_id` — not a parallel branch — drive that task to three unsuccessful attempts. Confirm the third unsuccessful result produces `FAILED_LIMIT`, no fourth attempt is dispatched, the terminal status is persisted in Notion before the final Slack post, and the workflow does not self-restart. A parallel branch's own exhaustion is governed separately by rule 10 (it stops only that branch, not the workflow, unless the branch is required for the merge) and is not what Test E3 exercises.
- **Test E4 — Turn limit:** using at least one parallel dispatch so branch turns count toward the same workflow-wide total (stop condition 4), run both of the following sub-cases:
  - **E4a (dispatch boundary):** drive the workflow to nineteen non-terminal turns such that Chris's next action would be a dispatch. Confirm the pre-dispatch budget check catches this before mentioning the next agent, so that dispatch never happens, and Chris stops with `TURN_LIMIT` instead.
  - **E4b (non-dispatch boundary):** with at least two other branches still in flight at turn 19, drive the workflow so the next event is an already-in-flight agent's result, or a Chris evaluation of it, rather than a new dispatch. Confirm that message is accepted and counted as turn 20, and that Chris enters the stopping state at that instant. With a third still-in-flight branch, post its result and mention Chris during the window between turn 20 landing and the terminal Notion write/Slack post actually completing; confirm that message is ignored under "Post-terminal messages" even though the terminal message has not yet been posted. Then let the remaining in-flight branch post its result and mention Chris after the terminal message; confirm that is ignored too. Confirm neither late message is counted, produces a new dispatch or terminal message, or reactivates the workflow.
  - For both sub-cases, confirm the terminal message itself is not counted as an additional turn, the terminal status is persisted in Notion before the final Slack post, and the workflow does not self-restart.

## Decision rule

- If Tests A-E pass using native Slack agents, no custom runtime is added for the MVP.
- If human mentions work but Bot-to-Bot mentions do not, design only a minimal relay for mention forwarding and loop-state enforcement.
- If official Slack agents are unavailable, reopen runtime options. Do not default automatically to Google Cloud or a local resident runner.

## Out of scope for the current MVP

- Local always-on Windows runner.
- Google Cloud deployment.
- Direct external AI API orchestration.
- Rebuilding a general workflow engine before the native-agent E2E result is known.
