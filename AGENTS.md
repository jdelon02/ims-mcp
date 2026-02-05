# IMS Agent Configuration

This project is wired to a local **Integrated Memory System (IMS)** backend
running on `http://localhost:8000`, with the following skills installed:

- `memory-core` – long-term, project-scoped memories (decisions, issues, key facts)
- `session-memory` – per-project, per-user, per-agent, per-task `SessionState`
- `context-rag` – unified context search across code, docs, and memories

**All agents** (Warp, Claude, MCP tools, CI bots, and any others) MUST treat
these IMS skills as the **primary mechanisms for memory and context** when
operating in this repository.

---

## 1. Identity & Scoping

When interacting with IMS-backed projects, agents MUST assume:

- `project_id = basename($PWD)` unless explicitly overridden.
- `user_id` is derived from the OS user or an explicit env var (e.g. `IMS_USER_ID`).
- `agent_id` reflects the current role, e.g.:
  - `planner` – planning/phase design
  - `implementer` – coding/implementation work
  - `debugger` – troubleshooting and bug-fixing
- `task_id` is a stable label for the current task (default `"default"`), e.g.:
  - `refactor-auth`, `fix-ci`, `add-reporting-endpoint`.

All IMS interactions (session + memory) MUST be scoped by this tuple:

> `(project_id, user_id, agent_id, task_id)`

We refer to this combination as the **session identity** (or simply the
**session** when the context is clear). All work MUST be associated with a
session identified by this tuple.

---

## 2. Context Retrieval (`context-rag` skill)

For any question or task about this project (including overviews, explanations,
planning, or debugging), agents MUST use the **`context-rag`** skill as the
primary way to gather context.

When invoking `context-rag`:

1. Set `project_id = basename($PWD)`.
2. Pass a natural-language `query` that describes the current question or task.
3. Include `sources` with at least `"memories"` and whichever of `"code"` / `"docs"`
   are relevant.
4. Use reasonable `per_source_limits` (e.g. `code=5`, `docs=5`, `memories=5`).
5. Take the returned `ContextHit.snippet` + key `metadata` and inject them into
   the prompt.

Agents MUST prefer **grounded answers** based on these `ContextHit` results over
speculation, and explicitly reference important prior decisions or facts found
in `memories` or `docs` hits.

Implementation detail: the `context-rag` skill internally talks to the IMS
backend; agents should treat the skill as the abstraction and MUST NOT call
underlying HTTP APIs directly.

---

## 3. Long-Term Memory (`memory-core` skill)

Agents MUST use the **`memory-core`** skill as the **long-term project brain**.

When important information arises:

- **Decisions** (architecture, data model, tooling):
  - Store via `memory-core` as `kind="decision"` with appropriate `tags`.
  - Example: "We store SessionState in Redis keyed by project/user/agent/task".
- **Bugs fixed**:
  - Store a `kind="issue"` memory summarizing:
    - Symptoms
    - Root cause
    - Fix
    - Any relevant files/functions
- **Stable configuration facts** (ports, URLs, credentials paths, feature flags):
  - Store as `kind="fact"` with tags like `config`, `env`, etc.

Before re-deriving solutions from scratch, agents SHOULD:

- Use the `memory-core` **find_memories** operation (directly or via
  `context-rag` with `sources` including `"memories"`) to look up existing
  decisions, issues, or facts.

Implementation detail: the `memory-core` skill internally talks to the IMS
backend; agents should call the skill and MUST NOT call underlying HTTP APIs
for storing or searching memories.

---

## 4. Session State (`session-memory` skill)

`session-memory` is **REQUIRED** in IMS projects.

Agents MUST use the **`session-memory`** skill to track progress and next
actions for each session `(project_id, user_id, agent_id, task_id)`.

### 4.1 Canonical session protocol

All agents and automations MUST use the `session-memory` skill in the following
step-by-step flow:

1. **Start or resume work – continue/auto session**

   At the beginning of a chat/run or work burst:

   - If you already know the session tuple or `session_id`, call the
     **continue_session** op for the relevant session
     `(project_id, user_id, agent_id, task_id)` to resolve or create the
     current session.
   - If the user starts a *new* chat and the first message clearly expresses a
     resume intent (e.g. "let's resume", "pick up where we left off",
     "pick up where we stopped", "keep going", "keep working") without
     specifying which task, use high-level helpers to discover the right
     session:
     - Prefer a `sessions.auto` / `auto_session` helper when available, which
       will internally call `list_open_sessions` and `resume_session`.
     - Otherwise, call `list_open_sessions` for the current
       `(project_id, user_id)`, ask the user which open session to resume when
       multiple are returned, and then call `resume_session` or
       `continue_session` with the chosen session.

2. **Do work using `SessionState.next_action`**

   - Use the returned `SessionState.next_action` (and related fields like
     `current_phase` / `current_stage`) to decide what to do next.
   - During work, keep an in-memory notion of `SessionState` and update it as
     progress is made.

3. **Pause, hand off, or finish – wrap session**

   Before pausing, switching tasks, or handing off to another agent:

   - Update the in-memory `SessionState` to reflect the new progress, including:
     - `current_phase` (e.g. `"Phase 3: Tasks API"`).
     - `current_stage` (Implementation / Verification / Debugging).
     - `last_checkpoint` (git hash or human label, if applicable).
     - `next_action` – a concrete, file/line-specific next step.
   - Persist the updated state via the `session-memory` **wrap_session** op for
     the same tuple.

4. **New chat with resume intent**

   - When a user starts a *new* chat and clearly expresses a resume intent
     without specifying a task, use `auto_session` or the
     `list_open_sessions` + `resume_session` pattern to re-attach to the
     correct session before doing any work.

### 4.2 Mandatory ordering

Before **any** interaction or work in this project (including answering
questions, planning, scanning specs, using `context-rag`, or editing code),
agents MUST:

1. Resolve the current session using `session-memory` (via `auto_session`,
   `continue_session`, or `resume_session`).
2. Read `SessionState` fields:
   - `current_phase`
   - `current_stage` (Implementation / Verification / Debugging)
   - `last_checkpoint`
   - `next_action`
3. Use `next_action` as the starting point for the interaction.

Before pausing or ending a work burst, agents MUST:

- Update `SessionState` to reflect new progress and a concrete next step,
  including `current_phase`, `current_stage`, `last_checkpoint`, and
  `next_action`.
- Persist the updated state via `wrap_session`.

### 4.3 Single source of truth & prohibited patterns

For any IMS-backed project, `session-memory` is the **single source of truth**
for session state for each session `(project_id, user_id, agent_id, task_id)`.

Agents and tools MUST NOT:

- Maintain separate, ad-hoc notions of "current task" or "current session"
  outside IMS.
- Start work without a resolved `SessionState` obtained via the
  `session-memory` skill.
- End work without persisting an updated `SessionState` via `session-memory`
  and surfacing an "IMS Session Wrap" summary.

Violation of these rules is considered an **IMS protocol error** and may result
in inconsistent or lost session memory across agents.

---

## 5. Session Observability Requirements

To make IMS session usage visible and auditable, agents working in this project
MUST surface their `session-memory` activity to the user.

### 5.1 Log lines for each operation

On **every session operation call**, agents MUST emit a concise log line
showing:

- The operation name: `auto_session`, `continue_session`, `wrap_session`,
  `list_open_sessions`, or `resume_session`.
- The resolved tuple `(project_id, user_id, agent_id, task_id)` when available.
- The returned `status` or `mode` and `session_id` when present.

### 5.2 IMS Session Resume summary

After resolving a session (via `auto_session`, `continue_session`, or
`resume_session`), agents MUST print a short **"IMS Session Resume"** summary
that includes at least:

- `project_id`, `user_id`, `agent_id`, `task_id`
- `session_id`
- `current_phase`
- `current_stage`
- `last_checkpoint` (if any)
- `next_action.description` (and `file_path` / `line_hint` when present)

Example format (agents may style, but MUST include these fields):

```text
IMS Session Resume
- project_id: <project_id>
- user_id: <user_id>
- agent_id: <agent_id>
- task_id: <task_id>
- session_id: <session_id>
- current_phase: <phase or "unset">
- current_stage: <stage or "unset">
- last_checkpoint: <hash/label or "none">
- next_action: <description> (@ <file_path>:<line_hint> if available)
```

### 5.3 IMS Session Wrap summary

Before calling the `session-memory` **wrap_session** op, agents MUST print an
**"IMS Session Wrap"** summary with the updated `SessionState`:

- `project_id`, `user_id`, `agent_id`, `task_id`
- `session_id`
- `current_phase`
- `current_stage`
- `last_checkpoint`
- `next_action.description` (and `file_path` / `line_hint` when present)

Example format:

```text
IMS Session Wrap
- session_id: <session_id>
- project_id: <project_id>
- user_id: <user_id>
- agent_id: <agent_id>
- task_id: <task_id>
- current_phase: <updated phase>
- current_stage: <updated stage>
- last_checkpoint: <new hash/label or "unchanged">
- next_action: <new concrete next action>
```

### 5.4 Protocol warnings

If an agent cannot resolve a session (no existing `SessionState`), it MUST:

- State explicitly that it is creating a new session, and
- Show the tuple `(project_id, user_id, agent_id, task_id)` it is using.

If, for any reason, an agent is unable to call `session-memory`, it MUST emit a
clear warning that the IMS session protocol is **not** being followed.

---

## 6. Interaction Between Memory Layers

Agents MUST understand and respect the separation of concerns between IMS
memory layers:

- **`context-rag`** is the **discovery layer**; use it to gather relevant
  code/docs/memories as `ContextHit` objects before reasoning.
- **`memory-core`** is the **long-term brain**; use it to store durable
  decisions, issues, and key facts, and to retrieve them before re-deriving.
- **`session-memory`** is the **working memory per task**; use it to keep
  track of where the agent is in a phase and what should happen next.

Agents MUST favor these IMS-backed skills over ad-hoc, file-based notes whenever
working inside this workspace.
