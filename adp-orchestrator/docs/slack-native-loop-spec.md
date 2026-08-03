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

## Roles

### Owner

- Defines purpose, priority, constraints, permissions, and final business decisions.
- Is contacted only when a Human Request stop condition is reached.

### Chris / Orchestrator Agent

- Receives the owner's initial mention.
- Reads relevant Notion and GitHub state.
- Converts the goal into tasks and acceptance criteria.
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
status: <planned|working|review|blocked|done|human_required>
summary: <short description>
result_links:
  - <Notion/GitHub/other evidence URL>
attempt: <integer starting at 1>
next_action: <explicit next action>
requires_human: <true|false>
```

Natural-language Slack messages may be used, but these fields must be inferable and should be included explicitly for multi-turn work.

## Standard loop

1. Owner mentions Chris with a goal.
2. Chris confirms the goal by writing acceptance criteria and a plan in the same thread.
3. Chris mentions one or more next agents.
4. Each agent performs work and returns evidence in the same thread while mentioning Chris.
5. Chris evaluates the evidence against the acceptance criteria.
6. Chris chooses one action:
   - assign the next task;
   - request correction;
   - request review;
   - approve completion;
   - create a Human Request;
   - stop due to loop protection.
7. Repeat until stopped.

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

Chris must state the expected responses and the merge condition before parallel dispatch.

### Correction loop

```text
Chris -> Claude -> Chris evaluates -> Claude correction -> Chris evaluates -> Done
```

## Stop conditions

A workflow stops when any condition is true:

1. Acceptance criteria are satisfied and evidence is recorded.
2. Human judgment, credentials, permissions, billing, or physical-device work is required.
3. The same task reaches three failed attempts.
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

The final message must include achieved results, unresolved items, evidence links, and the next human action when applicable.

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

### Test B: Chris to Claude

- Chris mentions Claude in the thread.
- Claude starts without a new human message.

### Test C: Claude to Chris

- Claude returns a result and mentions Chris.
- Chris resumes without a new human message.

### Test D: Correction loop

- Chris requests one correction.
- Claude returns the correction.
- Chris closes the workflow.

### Test E: Stop control

- Trigger Human Request, repeated result, or maximum-attempt condition.
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
