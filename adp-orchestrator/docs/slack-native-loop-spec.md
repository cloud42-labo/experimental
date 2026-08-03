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
status: <planned|working|review|blocked|failed|done|human_required>
summary: <short description>
result_links:
  - <Notion/GitHub/other evidence URL>
attempt: <integer starting at 1>
next_action: <explicit next action>
requires_human: <true|false>
```

Natural-language Slack messages may be used, but these fields must be inferable and should be included explicitly for multi-turn work.

## Attempt lifecycle

`attempt` counts unsuccessful execution attempts for the same `workflow_id + task_id + acceptance scope`, independent of which agent is assigned. There is exactly one attempt counter per task; it is not tracked separately per agent.

1. The first dispatch of the task, to any agent, starts at `attempt: 1`.
2. `planned`, `working`, and progress updates for that dispatch retain the same attempt number.
3. Slack delivery retries, duplicate event delivery, reconnects, and transport failures do not increment the attempt.
4. An attempt is unsuccessful when either:
   - the assigned agent returns `failed`; or
   - the assigned agent returns `done` or `review`, but Chris rejects the evidence because the stated acceptance criteria are not met.
5. When Chris redispatches the same task after an unsuccessful attempt, the attempt increments by one, regardless of whether the redispatch goes to the same agent or a different agent. Reassigning to a different agent does not reset or start a separate counter.
6. A `blocked` result does not increment the attempt counter, because it is not one of the unsuccessful predicates in rule 4. When Chris resolves the blocker, the resumed dispatch keeps the same attempt number that was active when the block occurred — it is not a new dispatch of the next attempt. A blocker consumes an attempt only if it is separately reclassified as unsuccessful (e.g. the agent reports it as `failed`, or Chris cannot resolve it and closes that attempt as rejected). If the blocker cannot be resolved, Chris stops with `HUMAN_REQUEST` or `CAPABILITY_FAILURE` without incrementing the attempt.
7. `human_required` stops the workflow immediately and does not consume another attempt.
8. After three unsuccessful attempts on the task, regardless of agent mix, Chris must stop with `FAILED_LIMIT`; a fourth execution attempt on that task is not permitted without the owner explicitly changing the goal or acceptance scope.
9. A material change to the goal or acceptance scope creates a new task or workflow rather than resetting the counter silently.
10. For parallel dispatch (see Graph patterns → Parallel and merge), each branch must use a distinct `task_id` (for example `<task_id>-claude`, `<task_id>-gemini`) so branch outcomes never share one counter and a branch's own attempt lifecycle follows rules 1-8 independently. The parent task has its own separate attempt counter that increments only when Chris evaluates the synthesized merge result against acceptance criteria and rejects it; an individual branch failing, by itself, does not increment the parent's counter. `FAILED_LIMIT` on a branch stops dispatch to that branch only, not the whole parallel task, unless the merge condition can no longer be satisfied.

## Notion persistence requirements

Chris must keep Notion synchronized at these control points:

1. Before the first agent dispatch: create or update the task with the goal, acceptance criteria, plan, assigned agent, and `In Progress` status.
2. At each material transition: record assignment changes, accepted evidence, rejected evidence, blockers, correction requests, and Human Requests.
3. Before posting a terminal Slack message: persist the terminal status, result summary, evidence links, unresolved items, and next human action when applicable.
4. If the terminal Notion write fails for any reason — unreachable, timed out, rejected for permissions, or rejected for validation — do not declare `COMPLETED`, and do not let the failed write block the owner-facing stop message. Rule 5 defines the fallback that applies in every one of these cases.
5. **Persistence-failure exception.** Whenever the terminal Notion write does not succeed, persistence-before-notification (rule 3) is waived for that one post so the workflow still has a valid stop path:
   - Chris posts the terminal Slack message anyway, labeled `persisted_to_notion: false` and naming the failure kind (`notion_unavailable`, `notion_permission_denied`, `notion_validation_rejected`, or similar);
   - the status used is `CAPABILITY_FAILURE` for unreachable/timeout failures Chris can retry unattended, and `HUMAN_REQUEST` for permission or validation failures, since those need the owner (or Notion schema/access owner) to act before a write can ever succeed;
   - the message includes everything that would normally go to Notion (goal, evidence links, unresolved items, next human action), since the Notion record does not yet exist;
   - once the underlying cause is resolved — Notion recovers, access is restored, or the schema/payload is fixed — Chris backfills the terminal record in Notion before the task is considered closed;
   - this exception only ever changes when persistence happens (after, instead of before, the terminal message); it never allows Chris to skip persisting altogether once the write can succeed.

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
3. The same task reaches three unsuccessful attempts as defined in the attempt lifecycle.
4. The workflow reaches twenty agent turns.
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

The final message must include achieved results, unresolved items, evidence links, the persisted Notion task link, and the next human action when applicable. Under the persistence-failure exception, the Notion task link is replaced by the full state inline in Slack, since no link exists yet.

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

- Trigger one of the following:
  - a Human Request;
  - the same instruction-result pair twice without new evidence; or
  - three unsuccessful attempts, where the third unsuccessful result produces `FAILED_LIMIT` and no fourth attempt is dispatched.
- Confirm the terminal status is persisted in Notion before the final Slack post.
- Confirm the workflow stops and does not self-restart.

## Decision rule

- If Tests A-E pass using native Slack agents, no custom runtime is added for the MVP.
- If human mentions work but Bot-to-Bot mentions do not, design only a minimal relay for mention forwarding and loop-state enforcement.
- If official Slack agents are unavailable, reopen runtime options. Do not default automatically to Google Cloud or a local resident runner.

## Out of scope for the current MVP

- Local always-on Windows runner.
- Google Cloud deployment.
- Direct external AI API orchestration.
- Rebuilding a general workflow engine before the native-agent E2E result is known.
