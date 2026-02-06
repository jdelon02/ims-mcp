"""MCP server for the Integrated Memory System (IMS).

This server exposes IMS capabilities (memory-core, session-memory, context-rag)
as MCP tools, allowing MCP-aware agents to interact with the IMS backend without
needing to know about HTTP APIs.

The server uses the official Model Context Protocol Python SDK
(https://github.com/modelcontextprotocol/python-sdk) and communicates with the
IMS backend via the included IMSClient.

Tool groups:
- ims.context-rag.*    → Unified search across code, docs, and memories
- ims.memory-core.*    → Long-term memory storage and retrieval
- ims.session-memory.* → Session state tracking and management

For usage guidelines and the complete IMS protocol, see AGENTS.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import FastMCP

# ---------------------------------------------------------------------------
# Environment loading (.env support)
# ---------------------------------------------------------------------------


def _load_env_from_file() -> None:
    """Load environment variables from a local .env-style file, if present.

    This is a minimal implementation to support local development without
    adding extra dependencies. Lines should be of the form KEY=VALUE.
    Existing environment variables are not overwritten.
    """

    # Allow override of the env file name/path via IMS_ENV_FILE; otherwise
    # default to ".env" in the same directory as this server.py file.
    env_setting = os.getenv("IMS_ENV_FILE", ".env")
    env_path = Path(env_setting)
    if not env_path.is_absolute():
        env_path = Path(__file__).resolve().parent / env_path

    if not env_path.exists():
        return

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # Fail open: if the .env file is malformed or unreadable, just ignore
        # it and rely on the existing environment.
        pass


# Load .env before we compute any IMS configuration.
_load_env_from_file()

# ---------------------------------------------------------------------------
# IMS client wiring
# ---------------------------------------------------------------------------

from app.ims_client import IMSClient


def _ims_client() -> IMSClient:
    """Construct an IMSClient using IMS_BASE_URL if set.

    This keeps configuration in one place and ensures all tools share the
    same base URL / timeout.
    """

    base_url = os.getenv("IMS_BASE_URL", "http://localhost:8000").rstrip("/")
    timeout = float(os.getenv("IMS_HTTP_TIMEOUT", "5.0"))
    client_name = os.getenv("IMS_CLIENT_NAME", "ims-mcp")
    verify_ssl = os.getenv("IMS_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
    return IMSClient(base_url=base_url, timeout=timeout, client_name=client_name, verify_ssl=verify_ssl)


# This name is what MCP clients will see.
mcp = FastMCP("IMS MCP")


# ---------------------------------------------------------------------------
# ims.context-rag tools
# ---------------------------------------------------------------------------

@mcp.tool("context_rag_context_search")
def ims_context_search(
    project_id: str,
    query: str,
    sources: Optional[List[str]] = None,
    per_source_limits: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Unified context search across code, docs, and memories for a project.

    Use this as the PRIMARY way to gather context before answering questions or
    starting work. Returns ContextHit objects with snippets and metadata.

    Args:
        project_id: Project identifier (typically basename of working directory)
        query: Natural-language description of what you're looking for
        sources: List of sources to search. Options: "code", "docs", "memories".
                 Include at least "memories" and relevant others.
        per_source_limits: Dict mapping source names to max results per source.
                          Example: {"code": 5, "docs": 5, "memories": 5}

    Returns:
        Dict with "results" key containing list of ContextHit objects, each with:
        - snippet: The actual text/code snippet
        - source: Which source it came from (code/docs/memories)
        - metadata: Additional context (file path, memory kind/tags, etc.)

    Example:
        results = ims_context_search(
            project_id="my-project",
            query="How is authentication implemented?",
            sources=["code", "memories"],
            per_source_limits={"code": 5, "memories": 5}
        )
    """

    ims = _ims_client()
    return ims.context_rag.context_search(
        project_id=project_id,
        query=query,
        sources=sources,
        per_source_limits=per_source_limits,
    )


# ---------------------------------------------------------------------------
# ims.memory-core tools
# ---------------------------------------------------------------------------

@mcp.tool("memory_core_store_memory")
def ims_store_memory(
    project_id: str,
    text: str,
    kind: str,
    tags: Optional[List[str]] = None,
    importance: Optional[float] = None,
) -> Dict[str, Any]:
    """Store a long-term memory for a project (decisions, issues, facts).

    Use this to persist important information that should be remembered across
    sessions and referenced later.

    Args:
        project_id: Project identifier
        text: Memory content - be clear and specific
        kind: Memory type. Use:
              - "decision": Architecture, data model, tooling choices
              - "issue": Bug fixes (symptoms, root cause, solution)
              - "fact": Stable config (ports, URLs, feature flags)
        tags: Optional categorization tags (e.g., ["auth", "backend"])
        importance: Optional 0.0-1.0 score for memory significance

    Returns:
        Dict with stored memory metadata including memory_id

    Examples:
        # Store architecture decision
        ims_store_memory(
            project_id="my-app",
            text="We use Redis for session storage, keyed by project/user/agent/task",
            kind="decision",
            tags=["architecture", "sessions"]
        )

        # Store bug fix
        ims_store_memory(
            project_id="my-app",
            text="MCP import error fixed by using FastMCP instead of Server class",
            kind="issue",
            tags=["mcp", "sdk-upgrade"]
        )
    """

    ims = _ims_client()
    return ims.memory_core.store_memory(
        project_id=project_id,
        text=text,
        kind=kind,
        tags=tags,
        importance=importance,
    )


@mcp.tool("memory_core_find_memories")
def ims_find_memories(
    project_id: str,
    query: str,
    kinds: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search long-term memories (decisions, issues, facts) for a project.

    Use this BEFORE re-deriving solutions to check if the problem has been
    solved before or if relevant decisions have been made.

    Args:
        project_id: Project identifier
        query: Natural-language search query
        kinds: Optional filter by memory types ("decision", "issue", "fact")
        tags: Optional filter by tags
        limit: Maximum number of results (default 10)

    Returns:
        List of memory dicts, each containing:
        - memory_id: Unique identifier
        - text: Memory content
        - kind: Memory type
        - tags: Associated tags
        - importance: Significance score
        - created_at: Timestamp

    Example:
        # Look up past auth decisions before implementing new auth
        memories = ims_find_memories(
            project_id="my-app",
            query="authentication implementation",
            kinds=["decision"],
            limit=5
        )
    """

    ims = _ims_client()
    return ims.memory_core.find_memories(
        project_id=project_id,
        query=query,
        kinds=kinds,
        tags=tags,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# ims.session-memory tools
# ---------------------------------------------------------------------------

@mcp.tool("session_memory_auto_session")
def ims_auto_session(
    project_id: str,
    user_message: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """High-level helper to automatically resume or create a session.

    Use this when the user says "let's resume", "pick up where we left off",
    "keep going", etc. without specifying which task. This tool intelligently
    determines whether to resume an existing session or create a new one.

    Args:
        project_id: Project identifier (typically basename($PWD))
        user_message: The user's actual message/request
        user_id: Optional user identifier (auto-detected if omitted)
        agent_id: Optional agent role (e.g., "planner", "implementer")

    Returns:
        Dict with:
        - status: "resumed" or "created"
        - mode: "resume" or "create"
        - session_id: Unique session identifier
        - state: SessionState dict with current_phase, current_stage, next_action

    Use continue_session instead if you know the specific (project, user, agent, task)
    tuple you want to work with.
    """

    ims = _ims_client()
    # SessionMemoryClient currently exposes only continue_session/wrap_session;
    # for now we call the HTTP endpoint directly via its base client.
    # When/if IMSClient gains an explicit auto_session helper, we can switch.
    with ims.session_memory._client("session-memory") as client:  # type: ignore[attr-defined]
        payload: Dict[str, Any] = {
            "project_id": project_id,
            "user_message": user_message,
        }
        if user_id is not None:
            payload["user_id"] = user_id
        if agent_id is not None:
            payload["agent_id"] = agent_id
        resp = client.post("/sessions/auto", json=payload)
        resp.raise_for_status()
        return resp.json()


@mcp.tool("session_memory_continue_session")
def ims_continue_session(
    project_id: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
    initial_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve or create a session for (project, user, agent, task) tuple.

    REQUIRED: Call this at the start of every work session to get the current
    SessionState. Use the returned next_action to decide what to do.

    Args:
        project_id: Project identifier (typically basename($PWD))
        user_id: User identifier (auto-detected from OS user if omitted)
        agent_id: Agent role (e.g., "planner", "implementer", "debugger")
        task_id: Task label (e.g., "refactor-auth", "fix-ci", default="default")
        initial_state: Optional initial SessionState if creating new session

    Returns:
        Dict with:
        - status: "resumed" (existing) or "created" (new)
        - session_id: Unique identifier for this session
        - state: SessionState dict containing:
            - current_phase: Current work phase
            - current_stage: "Implementation", "Verification", or "Debugging"
            - last_checkpoint: Last git hash or progress marker
            - next_action: Dict with description, file_path, line_hint

    Example:
        result = ims_continue_session(
            project_id="my-app",
            agent_id="implementer",
            task_id="add-auth"
        )
        next_step = result["state"]["next_action"]["description"]
    """

    ims = _ims_client()
    return ims.session_memory.continue_session(
        project_id=project_id,
        user_id=user_id,
        agent_id=agent_id,
        task_id=task_id,
        initial_state=initial_state,
    )


@mcp.tool("session_memory_wrap_session")
def ims_wrap_session(
    project_id: str,
    state: Dict[str, Any],
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist updated SessionState before pausing, switching tasks, or finishing.

    REQUIRED: Call this before ending work to save progress and set next_action
    for the next session.

    Args:
        project_id: Project identifier
        state: Updated SessionState dict with:
               - current_phase: Updated phase description
               - current_stage: "Implementation", "Verification", or "Debugging"
               - last_checkpoint: New git hash or progress marker
               - next_action: Dict with concrete next step:
                   - description: What to do next (be specific)
                   - file_path: File to work on (if applicable)
                   - line_hint: Line number (if applicable)
        user_id: Optional user identifier (uses state.user_id if omitted)
        agent_id: Optional agent identifier
        task_id: Optional task identifier

    Returns:
        Dict with:
        - status: "wrapped"
        - session_id: Session identifier
        - state: Persisted SessionState

    Example:
        updated_state = current_state.copy()
        updated_state["current_phase"] = "Phase 3: API Implementation"
        updated_state["current_stage"] = "Implementation"
        updated_state["next_action"] = {
            "description": "Implement POST /api/auth/login endpoint",
            "file_path": "src/routes/auth.ts",
            "line_hint": 45
        }
        ims_wrap_session(project_id="my-app", state=updated_state)
    """

    ims = _ims_client()
    return ims.session_memory.wrap_session(
        project_id=project_id,
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        task_id=task_id,
    )


@mcp.tool("session_memory_list_open_sessions")
def ims_list_open_sessions(
    project_id: str,
    user_id: Optional[str] = None,
    only_open: bool = True,
) -> Dict[str, Any]:
    """List open sessions for a project and user.

    Use this when the user wants to resume work but doesn't specify which task,
    and you need to show them their open sessions to choose from.

    Args:
        project_id: Project identifier
        user_id: User identifier (auto-detected if omitted)
        only_open: If True, only return sessions not marked complete (default: True)

    Returns:
        Dict with "sessions" key containing list of session summaries:
        - session_id: Unique identifier
        - project_id, user_id, agent_id, task_id: Session tuple
        - state: SessionState with current_phase, next_action, etc.
        - created_at, updated_at: Timestamps

    Example:
        sessions = ims_list_open_sessions(project_id="my-app")
        for s in sessions["sessions"]:
            print(f"{s['task_id']}: {s['state']['next_action']['description']}")
    """

    ims = _ims_client()
    with ims.session_memory._client("session-memory") as client:  # type: ignore[attr-defined]
        payload: Dict[str, Any] = {"project_id": project_id, "only_open": only_open}
        if user_id is not None:
            payload["user_id"] = user_id
        resp = client.post("/sessions/list_open", json=payload)
        resp.raise_for_status()
        return resp.json()


@mcp.tool("session_memory_resume_session")
def ims_resume_session(session_id: str) -> Dict[str, Any]:
    """Resume a specific session by its session_id.

    Use this after calling list_open_sessions when the user has chosen which
    session to continue working on.

    Args:
        session_id: The unique session identifier (from list_open_sessions)

    Returns:
        Dict with:
        - status: "resumed"
        - session_id: The session identifier
        - project_id, user_id, agent_id, task_id: Session tuple
        - state: SessionState with current_phase, current_stage, next_action

    Example:
        # User picks session from list
        result = ims_resume_session(session_id="abc123-def456")
        next_step = result["state"]["next_action"]["description"]
    """

    ims = _ims_client()
    with ims.session_memory._client("session-memory") as client:  # type: ignore[attr-defined]
        resp = client.post("/sessions/resume", json={"session_id": session_id})
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    # For now, run on stdio so MCP clients can spawn this as a subprocess.
    # Later we can switch to or add streamable HTTP transport if desired.
    mcp.run()
