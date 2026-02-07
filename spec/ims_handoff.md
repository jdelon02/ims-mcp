# IMS Handoff (ims_handoff)

## Goal
Provide a reliable, **cross-project handoff protocol** so an agent operating in one repo (e.g. `ims-mcp`) can leave actionable instructions for work to be done in another repo (e.g. `integrated-memory-system`) **without editing README.md** or relying on fragile, ad-hoc file pointers.

## Key idea
Use IMS’s canonical layers as the handoff substrate:

1. **task-memory** (GitHub Issues) = the durable task list + executable requirements
2. **memory-core** (Postgres/Qdrant) = durable rationale / decision / issue trail
3. **session-memory** (Redis SessionState) = “where to pick up next” in a specific agent/task session

The MCP server (`ims-mcp`) should expose a single high-level tool (proposed) that performs all three.

## Why not README.md instructions?
README updates are great for stable documentation, but poor for:

- ephemeral coordination
- multi-repo change choreography
- maintaining a single authoritative task list

Handoffs should be durable, queryable, and discoverable via IMS primitives.

---

## Proposed MCP tool: `ims.handoff.create`

### Behavior (high-level)
Given a source project, target project, and a structured “handoff packet”, the tool:

1. Resolves the **issue tracker repo** for the target project (may differ from the target project’s VCS remote).
2. Creates a GitHub Issue in the resolved **issue tracker repo** via IMS `task-memory`.
3. Stores a `memory-core` note in the **target project_id** summarizing:
   - why the work is needed
   - constraints/invariants
   - links to the GitHub Issue and any source PR/commit references
4. Seeds (or updates) a `session-memory` session in the **target project** and sets `SessionState.next_action` to reference the GitHub Issue.

### Repo resolution (GitHub vs Pantheon upstream)
A project’s **VCS remote** (where code is pushed/pulled) is not always the same as the **issue tracker repo** (where GitHub Issues live).

Examples:
- GitHub-hosted project:
  - VCS remote: GitHub
  - Issue tracker repo: same GitHub repo
- Pantheon-hosted project:
  - VCS remote: Pantheon
  - Issue tracker repo: an upstream GitHub repo (issues are created upstream)

The handoff tool MUST resolve the target issue repo using the following precedence:

1. Explicit input override (preferred)
   - `issues_github_repo` in the handoff input (format `owner/repo`).
2. Target project registry lookup (recommended)
   - A backend project registry (e.g. Postgres) keyed by `project_id` that stores:
     - `issues_github_repo` (format `owner/repo`)
     - `vcs_provider` (e.g. `github`, `pantheon`, `none`)
     - `is_isolated` (see Isolation below)
3. Fallback convention (last resort)
   - Assume `issues_github_repo = <default_owner>/<to_project_id>` and emit a warning.

If the target project’s VCS provider is Pantheon and no `issues_github_repo` can be resolved, the tool MUST fail with a clear error (since issues cannot be created in Pantheon).

### Isolation (Option A)
Some projects must be completely isolated (e.g. academic work) to prevent accidental context mixing.

Rules:
- The handoff tool MUST treat isolation as an opt-out from implicit cross-project context.
- Isolation does not prevent creating a task in a GitHub tracker when the user explicitly requests a handoff to that target project_id.
- Isolated projects MUST NOT participate in implicit “related projects” matching or context expansion.

Concretely:
- The handoff tool MUST NOT enable any “include related projects” / scope expansion behavior for isolated targets.
- Any project-intake workflow MUST NOT create or store related-project relationship edges for isolated projects (Option A).

### Input shape (suggested)
```json
{
  "from_project_id": "ims-mcp",
  "to_project_id": "integrated-memory-system",

  // Optional override to bypass registry/fallback resolution.
  // Format: "owner/repo"
  "issues_github_repo": "jdelon02/integrated-memory-system",

  "subject": "Add related-project discovery endpoints",
  "description": "Implement project_relationships table + /projects/related API ...",
  "tags": ["handoff", "integration"],
  "priority": "high",
  "links": {
    "source_repo": "jdelon02/ims-mcp",
    "source_ref": "<commit-hash-or-branch>",
    "docs": ["spec/ims_handoff.md"]
  },
  "seed_session": {
    "agent_id": "implementer",
    "task_id": "handoff-<opaque>",
    "current_phase": "Handoff",
    "current_stage": "Implementation"
  }
}
```

### Output shape (suggested)
```json
{
  "task": {
    "id": "gh-jdelon02/integrated-memory-system-123",
    "metadata": {
      "github_repo": "jdelon02/integrated-memory-system",
      "github_issue": 123,
      "github_url": "https://github.com/jdelon02/integrated-memory-system/issues/123"
    }
  },
  "memory": { "memory_id": "<uuid>" },
  "seeded_session": {
    "project_id": "integrated-memory-system",
    "agent_id": "implementer",
    "task_id": "handoff-<opaque>",
    "session_id": "<uuid>"
  }
}
```

---

## Session-memory convention: GitHub Issue ID as `next_action`

### Requirement
When the handoff tool seeds a target session, it MUST set `SessionState.next_action` to contain the GitHub-backed task identifier.

### Recommended representation (no backend schema changes)
Because `SessionState.next_action` currently supports:

- `description: string`
- `file_path?: string`
- `line_hint?: int`

…the simplest durable convention is:

- `next_action.description = "Work on task <task_id>: <subject>"`
- `state.metadata.current_task_id = <task_id>`
- `state.metadata.current_task_url = <github_url>`

Example:
```json
{
  "next_action": {
    "description": "Work on task gh-jdelon02/integrated-memory-system-123: Add related-project discovery endpoints"
  },
  "metadata": {
    "current_task_id": "gh-jdelon02/integrated-memory-system-123",
    "current_task_url": "https://github.com/jdelon02/integrated-memory-system/issues/123",
    "handoff_from_project_id": "ims-mcp"
  }
}
```

### Optional enhancement (requires backend change)
Extend the `NextAction` model in the IMS backend to support structured task references:

- `task_id?: string`
- `task_url?: string`

This avoids parsing strings and makes handoffs more robust.

---

## Agent workflow (receiving repo)

When an agent starts work in the **target repo**:

1. Resolve session via session-memory (`continue_session` or `auto_session`).
2. If `state.metadata.current_task_id` exists, fetch the GitHub Issue via task-memory.
3. Use context-rag to retrieve:
   - the `docs/PROJECT.md` project definition
   - the stored memory-core handoff note
   - any linked spec(s)
4. Implement the task and update:
   - GitHub Issue status
   - session-memory `next_action`
   - optionally store a memory-core `issue`/`decision` on completion

---

## Relationship to `docs/PROJECT.md`

`docs/PROJECT.md` (generated via project-intake) should include, at minimum:

- `ims.is_isolated` (boolean)
- `ims.vcs.provider` and `ims.vcs.remote_url` (for provenance)
- `ims.issues.github_repo` (format `owner/repo`) when tasks should be created in GitHub
  - for Pantheon-hosted projects this should point to the upstream GitHub repo

For isolated projects (Option A):

- project-intake MUST NOT create/store related-project relationship edges
- the handoff tool MUST NOT use implicit related-project expansion

Note: `related_projects` can still exist for non-isolated projects to drive future related-scope context retrieval, but is not required for the handoff tool itself.

---

## Implementation notes

### Where this lives
- This spec belongs to `ims-mcp` because `ims-mcp` is the agent-facing orchestration layer.

### Dependencies
- IMS backend must expose:
  - `/tasks/*` endpoints (GitHub-backed)
  - `/memories/*` endpoints
  - `/sessions/*` endpoints

### Observability
The handoff tool MUST log:
- created task id + URL
- stored memory id
- seeded session tuple + session_id
