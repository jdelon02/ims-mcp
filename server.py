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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
try:
    import pwd
except ImportError:  # pragma: no cover - non-POSIX fallback
    pwd = None  # type: ignore[assignment]

import httpx

from mcp.server import FastMCP

from app.meili_docs_indexer import index_directory_docs

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

    base_url = os.getenv("IMS_BASE_URL", "https://ims.delongpa.com").rstrip("/")
    timeout = float(os.getenv("IMS_HTTP_TIMEOUT", "5.0"))
    client_name = os.getenv("IMS_CLIENT_NAME", "ims-mcp")
    verify_ssl = os.getenv("IMS_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
    return IMSClient(base_url=base_url, timeout=timeout, client_name=client_name, verify_ssl=verify_ssl)


# This name is what MCP clients will see.
mcp = FastMCP("IMS MCP")

def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 with Z suffix."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def _default_user_id() -> str:
    """Resolve a stable local user identifier for session scoping."""

    explicit = (os.getenv("IMS_USER_ID") or "").strip()
    if explicit:
        return explicit

    if pwd is not None:
        try:
            local_user = pwd.getpwuid(os.getuid()).pw_name
            if local_user:
                return local_user
        except Exception:
            pass

    for key in ("LOGNAME", "USER", "USERNAME"):
        value = (os.getenv(key) or "").strip()
        if value:
            return value

    return "default"


def _post_json_probe(client: httpx.Client, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST to an IMS endpoint and return a compact health probe result."""

    try:
        resp = client.post(path, json=payload)
        from app.ims_client import _raise_for_status_with_body  # local import to avoid tool startup cycles

        _raise_for_status_with_body(resp)
        body: Any = None
        try:
            body = resp.json()
        except Exception:
            body = None

        probe: Dict[str, Any] = {"ok": True, "status_code": resp.status_code}
        if isinstance(body, dict):
            if isinstance(body.get("results"), list):
                probe["result_count"] = len(body["results"])
            if isinstance(body.get("sessions"), list):
                probe["session_count"] = len(body["sessions"])
        return probe
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _list_open_sessions_payload(
    project_id: str,
    user_id: Optional[str] = None,
    only_open: bool = True,
) -> Dict[str, Any]:
    """Read open sessions from session-memory backend."""
    resolved_user_id = (user_id or "").strip() or _default_user_id()

    ims = _ims_client()
    with ims.session_memory._client("session-memory") as client:  # type: ignore[attr-defined]
        payload: Dict[str, Any] = {
            "project_id": project_id,
            "only_open": only_open,
            "user_id": resolved_user_id,
        }
        resp = client.post("/sessions/list_open", json=payload)
        from app.ims_client import _raise_for_status_with_body  # local import to avoid tool startup cycles

        _raise_for_status_with_body(resp)
        return resp.json()


def _extract_session_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize session payload shape from auto/continue/resume responses."""

    if isinstance(result.get("state"), dict):
        return {
            "session_id": result.get("session_id"),
            "state": result.get("state"),
            "status": result.get("status"),
            "mode": result.get("mode"),
        }

    session_obj = result.get("session")
    if isinstance(session_obj, dict) and isinstance(session_obj.get("state"), dict):
        return {
            "session_id": session_obj.get("session_id") or result.get("session_id"),
            "state": session_obj.get("state"),
            "status": session_obj.get("status") or result.get("status"),
            "mode": result.get("mode"),
        }

    return {}


def _check_active_session(project_id: str) -> None:
    """Check if an active session exists for the project; raise if not.
    
    This enforces the IMS protocol requirement that all work must be done
    within an active session. Call this before non-session-memory operations.
    
    Raises:
        RuntimeError: If no active session exists for the project.
    """
    ims = _ims_client()
    with ims.session_memory._client("session-memory") as client:  # type: ignore[attr-defined]
        try:
            resp = client.get(f"/sessions/active/{project_id}")
            if resp.status_code == 404:
                raise RuntimeError(
                    f"No active session for project '{project_id}'. "
                    "You must resolve a session first using auto_session, continue_session, or resume_session."
                )
            from app.ims_client import _raise_for_status_with_body
            _raise_for_status_with_body(resp)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise RuntimeError(
                    f"No active session for project '{project_id}'. "
                    "You must resolve a session first using auto_session, continue_session, or resume_session."
                ) from exc
            raise


def _find_bound_session(
    sessions: List[Dict[str, Any]],
    hook_session_id: str,
) -> Optional[Dict[str, Any]]:
    """Find the first session whose metadata binds to hook_session_id."""

    if not hook_session_id:
        return None

    for sess in sessions:
        if not isinstance(sess, dict):
            continue

        state_obj = sess.get("state") if isinstance(sess.get("state"), dict) else {}
        metadata_candidates: List[Dict[str, Any]] = []
        for maybe in (sess.get("metadata"), state_obj.get("metadata")):
            if isinstance(maybe, dict):
                metadata_candidates.append(maybe)

        for metadata in metadata_candidates:
            for key in ("hook_session_id", "claude_session_id", "client_session_id"):
                if metadata.get(key) == hook_session_id:
                    return sess

    return None


# ---------------------------------------------------------------------------
# MCP resources (read-only context surfaces)
# ---------------------------------------------------------------------------

@mcp.resource(
    "ims://health",
    title="IMS Health",
    description="Runtime health snapshot for IMS backend components.",
    mime_type="application/json",
)
def ims_health_resource() -> Dict[str, Any]:
    """Expose read-only backend health checks as an MCP resource."""

    ims = _ims_client()
    probe_project_id = (
        os.getenv("IMS_HEALTH_PROJECT_ID")
        or os.getenv("IMS_DEFAULT_PROJECT_ID")
        or os.getenv("IMS_PROJECT_ID")
        or "ims-mcp"
    )

    checks: Dict[str, Any] = {}
    with ims.session_memory._client("session-memory") as client:  # type: ignore[attr-defined]
        checks["session_memory"] = _post_json_probe(
            client,
            "/sessions/list_open",
            {"project_id": probe_project_id, "only_open": True},
        )
    with ims.memory_core._client("memory-core") as client:  # type: ignore[attr-defined]
        checks["memory_core"] = _post_json_probe(
            client,
            "/memories/search",
            {"project_id": probe_project_id, "query": "health check", "limit": 1},
        )
    with ims.context_rag._client("context-rag") as client:  # type: ignore[attr-defined]
        checks["context_rag"] = _post_json_probe(
            client,
            "/context/search",
            {
                "project_id": probe_project_id,
                "query": "health check",
                "sources": ["memories"],
                "per_source_limits": {"memories": 1},
            },
        )

    overall_status = "ok" if all(c.get("ok") for c in checks.values()) else "degraded"
    return {
        "status": overall_status,
        "checked_at": _utc_now_iso(),
        "ims_base_url": ims.base_url,
        "timeout_seconds": ims.timeout,
        "verify_ssl": ims.verify_ssl,
        "probe_project_id": probe_project_id,
        "checks": checks,
    }


@mcp.resource(
    "ims://capabilities",
    title="IMS Capabilities",
    description="Discover available tools/resources and server configuration.",
    mime_type="application/json",
)
async def ims_capabilities_resource() -> Dict[str, Any]:
    """Expose server/tool/resource capability metadata."""

    ims = _ims_client()
    tools = await mcp.list_tools()
    resources = await mcp.list_resources()
    resource_templates = await mcp.list_resource_templates()

    def _compact(item: Any, keys: List[str]) -> Dict[str, Any]:
        data = item.model_dump() if hasattr(item, "model_dump") else {}
        return {k: data[k] for k in keys if data.get(k) is not None}

    return {
        "server": {"name": "IMS MCP"},
        "generated_at": _utc_now_iso(),
        "backend": {
            "ims_base_url": ims.base_url,
            "timeout_seconds": ims.timeout,
            "verify_ssl": ims.verify_ssl,
        },
        "counts": {
            "tools": len(tools),
            "resources": len(resources),
            "resource_templates": len(resource_templates),
        },
        "tools": [_compact(t, ["name", "title", "description"]) for t in tools],
        "resources": [_compact(r, ["uri", "name", "title", "description", "mimeType"]) for r in resources],
        "resource_templates": [
            _compact(t, ["uriTemplate", "name", "title", "description", "mimeType"]) for t in resource_templates
        ],
    }


@mcp.resource(
    "ims://sessions/{project_id}/open",
    title="Open Sessions Snapshot (project)",
    description="Open sessions snapshot for a project using inferred user context.",
    mime_type="application/json",
)
def ims_open_sessions_snapshot(project_id: str) -> Dict[str, Any]:
    """Expose a read-only open-sessions snapshot by project_id."""
    resolved_user_id = _default_user_id()
    payload = _list_open_sessions_payload(project_id=project_id, user_id=resolved_user_id, only_open=True)
    sessions = payload.get("sessions", []) if isinstance(payload, dict) else []
    return {
        "snapshot_at": _utc_now_iso(),
        "project_id": project_id,
        "user_id": resolved_user_id,
        "only_open": True,
        "count": len(sessions) if isinstance(sessions, list) else 0,
        "sessions": sessions,
    }


@mcp.resource(
    "ims://sessions/{project_id}/{user_id}/open",
    title="Open Sessions Snapshot (project + user)",
    description="Open sessions snapshot for an explicit project_id and user_id.",
    mime_type="application/json",
)
def ims_open_sessions_snapshot_for_user(project_id: str, user_id: str) -> Dict[str, Any]:
    """Expose a read-only open-sessions snapshot by project_id and user_id."""

    payload = _list_open_sessions_payload(project_id=project_id, user_id=user_id, only_open=True)
    sessions = payload.get("sessions", []) if isinstance(payload, dict) else []
    return {
        "snapshot_at": _utc_now_iso(),
        "project_id": project_id,
        "user_id": user_id,
        "only_open": True,
        "count": len(sessions) if isinstance(sessions, list) else 0,
        "sessions": sessions,
    }


# ---------------------------------------------------------------------------
# ims.context-rag tools
# ---------------------------------------------------------------------------

@mcp.tool("context_rag_context_search")
def ims_context_search(
    project_id: str,
    query: str,
    sources: Optional[List[str]] = None,
    per_source_limits: Optional[Dict[str, int]] = None,
    user_id: Optional[str] = None,
    expand_graph: bool = True,
    graph_depth: int = 2,
) -> Dict[str, Any]:
    """Unified context search across code, docs, and memories with optional graph expansion.

    Use this as the PRIMARY way to gather context before answering questions or
    starting work. Returns ContextHit objects with snippets and metadata.
    
    Enhanced to include graph relationship expansion for richer context when
    expand_graph is enabled.

    Args:
        project_id: Project identifier (typically basename of working directory)
        query: Natural-language description of what you're looking for
        sources: List of sources to search. Options: "code", "docs", "memories".
                 Include at least "memories" and relevant others.
        per_source_limits: Dict mapping source names to max results per source.
                          Example: {"code": 5, "docs": 5, "memories": 5}
        expand_graph: Whether to expand via graph relationships (default: True).
                     When enabled, vector search results are enriched with related
                     entities from the ontology graph.
        graph_depth: How deep to traverse relationships (1-3, default: 2).
                    Higher values return more context but may be slower.

    Returns:
        Dict with "results" key containing list of ContextHit objects, each with:
        - snippet: The actual text/code snippet
        - source: Which source it came from (code/docs/memories)
        - metadata: Additional context (file path, memory kind/tags, etc.)
        
        When expand_graph=True, results include graph-expanded context with
        related decisions, components, and bugs.

    Examples:
        # Vector search with graph expansion (default)
        results = ims_context_search(
            project_id="my-project",
            query="How is authentication implemented?",
            sources=["code", "memories"],
            per_source_limits={"code": 5, "memories": 5},
            expand_graph=True,
            graph_depth=2
        )
        
        # Vector-only search (no graph expansion)
        results = ims_context_search(
            project_id="my-project",
            query="authentication",
            sources=["code"],
            expand_graph=False
        )
    """
    # Enforce active session requirement
    _check_active_session(project_id)
    
    ims = _ims_client()
    return ims.context_rag.context_search(
        project_id=project_id,
        query=query,
        sources=sources,
        per_source_limits=per_source_limits,
        user_id=user_id,
        expand_graph=expand_graph,
        graph_depth=graph_depth,
    )


# ---------------------------------------------------------------------------
# Meilisearch docs indexing
# ---------------------------------------------------------------------------

@mcp.tool("docs_index_directory")
def docs_index_directory(
    root_dir: str,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    index_uid: str = "project_docs",
    exts: Optional[List[str]] = None,
    max_bytes: int = 2_000_000,
    prune_dirs: Optional[List[str]] = None,
    include_globs: Optional[List[str]] = None,
    exclude_globs: Optional[List[str]] = None,
    no_default_excludes: bool = False,
    chunking: bool = True,
    chunk_max_chars: int = 4000,
    snippet_chars: int = 400,
    batch_size: int = 100,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Index a directory of docs into Meilisearch (chunked by default).

    This is intended to populate the `project_docs` index that IMS context-rag
    reads from when retrieving `docs` hits.

    Environment variables used:
    - IMS_MEILI_URL (required)
    - IMS_MEILI_API_KEY (optional)
    - IMS_USER_ID (optional; used if user_id is omitted)

    Args:
        root_dir: Directory to index recursively.
        project_id: Defaults to basename(root_dir).
        user_id: Defaults to IMS_USER_ID else OS username.
        index_uid: Meilisearch index uid (default: project_docs).
        exts: List of extensions to include (e.g. [".md", ".txt"]).
        max_bytes: Skip files larger than this.
        prune_dirs: Directory names to prune (defaults include .git, node_modules, .venv, etc.).
        chunking: If true, split into chunks and store 1 chunk = 1 Meili doc.
        chunk_max_chars: Approx max characters per chunk.
        snippet_chars: Max characters stored in the `snippet` field.
        batch_size: Upsert request batch size.
        dry_run: If true, only return stats; do not call Meilisearch.

    Returns:
        A dict with stats and (if not dry_run) Meilisearch task info.
    """

    return index_directory_docs(
        root_dir=root_dir,
        project_id=project_id,
        user_id=user_id,
        index_uid=index_uid,
        exts=exts,
        max_bytes=max_bytes,
        prune_dirs=prune_dirs,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        no_default_excludes=no_default_excludes,
        chunking=chunking,
        chunk_max_chars=chunk_max_chars,
        snippet_chars=snippet_chars,
        batch_size=batch_size,
        dry_run=dry_run,
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
    
    Enhanced with ontology graph integration: When kind="decision" or kind="issue",
    the backend automatically creates corresponding graph nodes (Decision or Bug)
    in the knowledge graph, enabling relationship tracking and impact analysis.

    Args:
        project_id: Project identifier
        text: Memory content - be clear and specific
        kind: Memory type. Use:
              - "decision": Architecture, data model, tooling choices
                           (auto-creates Decision graph node)
              - "issue": Bug fixes (symptoms, root cause, solution)
                        (auto-creates Bug graph node)
              - "fact": Stable config (ports, URLs, feature flags)
                       (memory only, no graph node)
        tags: Optional categorization tags (e.g., ["auth", "backend"])
        importance: Optional 0.0-1.0 score for memory significance

    Returns:
        Dict with stored memory metadata including memory_id
    
    Behavior:
        - kind="decision" → creates memory in Postgres + embedding in Qdrant + Decision node in Neo4j
        - kind="issue" → creates memory in Postgres + embedding in Qdrant + Bug node in Neo4j
        - kind="note"/"fact" → creates memory in Postgres + embedding in Qdrant only

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
    # Enforce active session requirement
    _check_active_session(project_id)
    
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
    # Enforce active session requirement
    _check_active_session(project_id)
    
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
    resolved_user_id = (user_id or "").strip() or _default_user_id()
    # SessionMemoryClient currently exposes only continue_session/wrap_session;
    # for now we call the HTTP endpoint directly via its base client.
    # When/if IMSClient gains an explicit auto_session helper, we can switch.
    with ims.session_memory._client("session-memory") as client:  # type: ignore[attr-defined]
        payload: Dict[str, Any] = {
            "project_id": project_id,
            "user_message": user_message,
            "user_id": resolved_user_id,
        }
        if agent_id is not None:
            payload["agent_id"] = agent_id
        resp = client.post("/sessions/auto", json=payload)
        resp.raise_for_status()
        return resp.json()

@mcp.tool("session_memory_resolve_session")
def ims_resolve_session(
    project_id: str,
    hook_session_id: str,
    user_message: str = "resume or start a session",
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
    resume_session_id: Optional[str] = None,
    force_new: bool = False,
) -> Dict[str, Any]:
    """Resolve and bind an IMS session to a hook/session identifier.

    This helper is intended for strict hook gating:
    - resolves a working session (resume or create),
    - writes `state.metadata.hook_session_id`,
    - persists the metadata via checkpoint_session.
    """

    ims = _ims_client()
    resolved_user_id = (user_id or "").strip() or _default_user_id()

    # Resolve session first (explicit resume, forced new, or auto behavior).
    if resume_session_id:
        base_result = ims_resume_session(session_id=resume_session_id)
    elif force_new:
        resolved_task_id = task_id or f"session-{uuid4().hex[:8]}"
        base_result = ims.session_memory.continue_session(
            project_id=project_id,
            user_id=resolved_user_id,
            agent_id=agent_id,
            task_id=resolved_task_id,
        )
    elif task_id is not None:
        base_result = ims.session_memory.continue_session(
            project_id=project_id,
            user_id=resolved_user_id,
            agent_id=agent_id,
            task_id=task_id,
        )
    else:
        base_result = ims_auto_session(
            project_id=project_id,
            user_message=user_message,
            user_id=resolved_user_id,
            agent_id=agent_id,
        )

    if isinstance(base_result, dict) and base_result.get("mode") == "choice_required":
        return {
            "status": "choice_required",
            "hook_session_id": hook_session_id,
            "project_id": project_id,
            "result": base_result,
        }

    normalized = _extract_session_payload(base_result if isinstance(base_result, dict) else {})
    state = normalized.get("state")
    if not isinstance(state, dict):
        return {
            "status": "error",
            "hook_session_id": hook_session_id,
            "project_id": project_id,
            "message": "Unable to normalize session payload from resolver response",
            "result": base_result,
        }

    metadata = state.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["hook_session_id"] = hook_session_id
    metadata["resolved_via"] = "session_memory_resolve_session"
    metadata["resolved_at"] = _utc_now_iso()
    metadata["hook_user_message"] = user_message
    state["metadata"] = metadata
    effective_user_id = (user_id or "").strip() or state.get("user_id") or _default_user_id()

    persisted = ims.session_memory.checkpoint_session(
        project_id=project_id,
        state=state,
        user_id=effective_user_id,
        agent_id=agent_id or state.get("agent_id"),
        task_id=task_id or state.get("task_id"),
    )

    return {
        "status": "resolved",
        "hook_session_id": hook_session_id,
        "project_id": project_id,
        "resolution": {
            "source_status": normalized.get("status"),
            "source_mode": normalized.get("mode"),
        },
        "session_id": persisted.get("session_id") or normalized.get("session_id"),
        "state": persisted.get("state", state),
    }


@mcp.tool("session_memory_get_bound_session")
def ims_get_bound_session(
    project_id: str,
    hook_session_id: str,
    user_id: Optional[str] = None,
    only_open: bool = True,
) -> Dict[str, Any]:
    """Get the IMS session currently bound to a hook session id."""

    payload = _list_open_sessions_payload(project_id=project_id, user_id=user_id, only_open=only_open)
    sessions_raw = payload.get("sessions", []) if isinstance(payload, dict) else []
    sessions = [s for s in sessions_raw if isinstance(s, dict)]

    bound = _find_bound_session(sessions=sessions, hook_session_id=hook_session_id)
    if not bound:
        return {
            "status": "not_found",
            "project_id": project_id,
            "hook_session_id": hook_session_id,
            "session": None,
            "session_count": len(sessions),
        }

    return {
        "status": "found",
        "project_id": project_id,
        "hook_session_id": hook_session_id,
        "session": bound,
        "session_count": len(sessions),
    }


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


@mcp.tool("session_memory_checkpoint_session")
def ims_checkpoint_session(
    project_id: str,
    state: Dict[str, Any],
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist updated SessionState mid-burst (checkpoint).

    Use this frequently while actively working to save progress without implying
    you are pausing/handing off. This is intended to reduce excessive wrap calls
    ("wrap chatter").

    Args:
        project_id: Project identifier
        state: Updated SessionState
        user_id: Optional user identifier
        agent_id: Optional agent identifier
        task_id: Optional task identifier

    Returns:
        Dict with:
        - status: "checkpointed"
        - session_id: Session identifier
        - state: Persisted SessionState
    """

    ims = _ims_client()
    return ims.session_memory.checkpoint_session(
        project_id=project_id,
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        task_id=task_id,
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
    return _list_open_sessions_payload(project_id=project_id, user_id=user_id, only_open=only_open)


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
        from app.ims_client import _raise_for_status_with_body  # local import to avoid tool startup cycles

        _raise_for_status_with_body(resp)
        return resp.json()


# ---------------------------------------------------------------------------
# ims.handoff tools
# ---------------------------------------------------------------------------

def _normalize_repo_full_name(val: str) -> str:
    v = (val or "").strip()
    if not v:
        return ""
    v = v.replace("https://github.com/", "").replace("http://github.com/", "")
    v = v.replace("github.com/", "")
    v = v.rstrip("/")
    if v.endswith(".git"):
        v = v[: -len(".git")]
    return v


def _default_github_owner() -> str:
    return (os.getenv("IMS_DEFAULT_GITHUB_OWNER") or os.getenv("IMS_GITHUB_OWNER") or "jdelon02").strip() or "jdelon02"


@mcp.tool("handoff_create")
def ims_handoff_create(
    *,
    from_project_id: str,
    to_project_id: str,
    subject: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    priority: str = "medium",
    issues_github_repo: Optional[str] = None,
    links: Optional[Dict[str, Any]] = None,
    seed_session: Optional[Dict[str, Any]] = None,
    to_user_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create a cross-project handoff.

    This orchestrates:
    - task-memory: creates a GitHub Issue (task) for the target project
    - memory-core: stores a durable handoff note under the target project_id
    - session-memory: seeds/updates a target session's next_action to reference the task id

    Repo resolution precedence:
    1) explicit issues_github_repo override (preferred)
    2) backend project registry lookup (/projects/{id})
    3) fallback convention: <default_owner>/<to_project_id>

    Fail-closed rules:
    - If registry says issues_provider=none, do not guess.
    - If registry says vcs_provider=pantheon and no issues mapping is present, require override.
    """

    ims = _ims_client()

    resolved_repo = _normalize_repo_full_name(issues_github_repo or "")
    registry: Optional[Dict[str, Any]] = None
    integration: Optional[Dict[str, Any]] = None

    if not resolved_repo:
        try:
            registry = ims.project_registry.get_project(project_id=to_project_id)
            integration = registry.get("integration") if isinstance(registry, dict) else None
        except httpx.HTTPStatusError as e:
            # If the project isn't in the registry yet (404), fall back.
            if e.response is None or e.response.status_code != 404:
                raise

        if integration:
            issues_provider = (integration.get("issues_provider") or "none").strip() or "none"
            vcs_provider = (integration.get("vcs_provider") or "none").strip() or "none"

            if issues_provider == "github":
                resolved_repo = _normalize_repo_full_name(integration.get("issues_github_repo") or "")
                if not resolved_repo:
                    raise RuntimeError("project registry: issues_provider=github but issues_github_repo is missing")

            elif issues_provider == "none":
                raise RuntimeError("project registry: issues_provider=none (refusing to guess issue repo; provide issues_github_repo override)")

            if vcs_provider == "pantheon" and not resolved_repo:
                # Pantheon cannot accept issues directly; caller must provide a mapping.
                raise RuntimeError("project registry: vcs_provider=pantheon requires issues_github_repo override or mapping")

            # If an upstream repo is provided (common for Pantheon), accept it as the repo override.
            if not resolved_repo:
                upstream = _normalize_repo_full_name(integration.get("upstream_github_repo") or "")
                if upstream:
                    resolved_repo = upstream

    if not resolved_repo:
        resolved_repo = f"{_default_github_owner()}/{to_project_id}"

    task_tags = list(tags or [])
    if "handoff" not in task_tags:
        task_tags.append("handoff")

    links = links or {}

    seed_session = seed_session or {}
    seed_agent_id = seed_session.get("agent_id") or "implementer"
    seed_task_id = seed_session.get("task_id") or f"handoff-{uuid4().hex[:8]}"
    current_phase = seed_session.get("current_phase") or "Handoff"
    current_stage = seed_session.get("current_stage") or "Implementation"

    # DRY RUN: return a plan without performing side effects (no GitHub issue,
    # no memory write, no session mutation).
    if dry_run:
        task_payload = {
            "project_id": to_project_id,
            "subject": subject,
            "description": description,
            "tags": task_tags,
            "priority": priority,
            "issues_github_repo": resolved_repo,
        }

        placeholder_task_id = f"gh-{resolved_repo}-<issue_number>"
        placeholder_task_url = f"https://github.com/{resolved_repo}/issues/<issue_number>"

        memory_lines = [
            f"Handoff from `{from_project_id}` → `{to_project_id}`",
            "",
            f"Task: `{placeholder_task_id}` ({placeholder_task_url})",
            "",
            "---",
            "",
            description or "(No description)",
            "",
        ]
        if links:
            memory_lines.append("Links:")
            for k, v in links.items():
                memory_lines.append(f"- {k}: {v}")
            memory_lines.append("")

        initial_state: Dict[str, Any] = {
            "project_id": to_project_id,
            "agent_id": seed_agent_id,
            "task_id": seed_task_id,
            "current_phase": current_phase,
            "current_stage": current_stage,
            "next_action": {
                "description": f"Work on task {placeholder_task_id}: {subject}",
            },
            "metadata": {
                "current_task_id": placeholder_task_id,
                "current_task_url": placeholder_task_url,
                "handoff_from_project_id": from_project_id,
            },
        }

        return {
            "dry_run": True,
            "resolved_issues_github_repo": resolved_repo,
            "registry": registry,
            "integration": integration,
            "would_create_task": task_payload,
            "would_store_memory": {
                "project_id": to_project_id,
                "kind": "note",
                "tags": task_tags,
                "importance": 0.4,
                "text": "\n".join(memory_lines),
            },
            "would_seed_session": {
                "project_id": to_project_id,
                "user_id": to_user_id,
                "agent_id": seed_agent_id,
                "task_id": seed_task_id,
                "initial_state": initial_state,
            },
        }

    # 1) Create task in GitHub-backed task-memory.
    task = ims.task_memory.create_task(
        project_id=to_project_id,
        subject=subject,
        description=description,
        tags=task_tags,
        priority=priority,
        issues_github_repo=resolved_repo,
    )

    task_id = task.get("id")
    task_url = (task.get("metadata") or {}).get("github_url")

    # 2) Store durable handoff note in memory-core under the target project.
    lines = [
        f"Handoff from `{from_project_id}` → `{to_project_id}`",
        "",
        f"Task: `{task_id}`" + (f" ({task_url})" if task_url else ""),
        "",
        "---",
        "",
        description or "(No description)",
        "",
    ]

    if links:
        lines.append("Links:")
        for k, v in links.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    memory = ims.memory_core.store_memory(
        project_id=to_project_id,
        text="\n".join(lines),
        kind="note",
        tags=task_tags,
        importance=0.4,
    )

    # 3) Seed/update a target session.
    initial_state: Dict[str, Any] = {
        "project_id": to_project_id,
        "user_id": to_user_id,
        "agent_id": seed_agent_id,
        "task_id": seed_task_id,
        "current_phase": current_phase,
        "current_stage": current_stage,
        "next_action": {
            "description": f"Work on task {task_id}: {subject}",
        },
        "metadata": {
            "current_task_id": task_id,
            "current_task_url": task_url,
            "handoff_from_project_id": from_project_id,
            "handoff_memory_id": memory.get("id"),
        },
    }

    # Don't send null user_id in the embedded state (let backend derive it).
    if initial_state["user_id"] is None:
        initial_state.pop("user_id")

    seeded = ims.session_memory.continue_session(
        project_id=to_project_id,
        user_id=to_user_id,
        agent_id=seed_agent_id,
        task_id=seed_task_id,
        initial_state=initial_state,
    )

    return {
        "dry_run": False,
        "resolved_issues_github_repo": resolved_repo,
        "task": task,
        "memory": {"id": memory.get("id")},
        "seeded_session": {
            "project_id": to_project_id,
            "user_id": to_user_id,
            "agent_id": seed_agent_id,
            "task_id": seed_task_id,
            "session_id": seeded.get("session_id"),
        },
    }


# ---------------------------------------------------------------------------
# ims.graph tools (ontology node creation)
# ---------------------------------------------------------------------------

@mcp.tool("graph_create_decision")
def ims_graph_create_decision(
    project_id: str,
    text: str,
    rationale: str,
    alternatives: Optional[List[str]] = None,
    consequences: Optional[List[str]] = None,
    importance: float = 0.5,
    tags: Optional[List[str]] = None,
) -> str:
    """Create a Decision node in the ontology graph.
    
    Use this to record architectural and technical decisions with their rationale.
    
    Args:
        project_id: Project identifier
        text: The decision made (min 10 chars)
        rationale: Why this decision was made (min 20 chars)
        alternatives: Options that were considered
        consequences: Expected outcomes and tradeoffs
        importance: Significance 0.0-1.0 (affects retention tier)
        tags: Categorization tags
    
    Returns:
        The UUID of the created Decision node
    
    Example:
        decision_id = ims_graph_create_decision(
            project_id="my-app",
            text="Use Redis for session state storage",
            rationale="Need atomic operations, TTL support, and multi-instance capability",
            alternatives=["File-based (rejected - no concurrency)"],
            consequences=["Requires Redis deployment", "Enables horizontal scaling"],
            importance=0.9,
            tags=["architecture", "redis", "session-state"]
        )
    """
    # Validate project_id
    if not project_id or not isinstance(project_id, str):
        raise ValueError("project_id must be a non-empty string")
    if not project_id.strip():
        raise ValueError("project_id cannot be empty or whitespace only")
    
    # Validate required field lengths
    if len(text.strip()) < 10:
        raise ValueError("text must be at least 10 characters")
    if len(rationale.strip()) < 20:
        raise ValueError("rationale must be at least 20 characters")
    if not 0.0 <= importance <= 1.0:
        raise ValueError("importance must be between 0.0 and 1.0")
    
    ims = _ims_client()
    properties: Dict[str, Any] = {
        "project_id": project_id,
        "text": text,
        "rationale": rationale,
        "importance": importance,
        "access_count": 0,
    }
    if alternatives:
        properties["alternatives"] = alternatives
    if consequences:
        properties["consequences"] = consequences
    if tags:
        properties["tags"] = tags
    
    node_id = ims.graph.create_node("Decision", properties)
    return node_id


@mcp.tool("graph_create_bug")
def ims_graph_create_bug(
    project_id: str,
    symptoms: str,
    status: str = "open",
    severity: str = "medium",
    root_cause: Optional[str] = None,
    fix: Optional[str] = None,
    primary_file: Optional[str] = None,
    line_hint: Optional[int] = None,
    external_id: Optional[str] = None,
    external_system: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> str:
    """Create a Bug node in the ontology graph.
    
    Use this to track bugs with symptoms, root cause, and resolution.
    
    Args:
        project_id: Project identifier
        symptoms: What's broken/wrong (min 10 chars)
        status: Bug lifecycle state (open, in_progress, blocked, fixed, wont_fix)
        severity: Impact level (low, medium, high, critical)
        root_cause: Why it's happening
        fix: How it was fixed
        primary_file: Main file where bug exists
        line_hint: Approximate line number
        external_id: Link to external system (e.g., "gh-owner/repo-123")
        external_system: External system type (e.g., "github", "jira")
        tags: Categorization tags
    
    Returns:
        The UUID of the created Bug node
    
    Example:
        bug_id = ims_graph_create_bug(
            project_id="my-app",
            symptoms="Server crashes on invalid JWT token",
            status="open",
            severity="high",
            root_cause="Missing null check in token validation",
            primary_file="auth/middleware.py",
            line_hint=42,
            tags=["auth", "crash"]
        )
    """
    # Validate project_id
    if not project_id or not isinstance(project_id, str):
        raise ValueError("project_id must be a non-empty string")
    if not project_id.strip():
        raise ValueError("project_id cannot be empty or whitespace only")
    
    # Validate required field lengths
    if len(symptoms.strip()) < 10:
        raise ValueError("symptoms must be at least 10 characters")
    
    # Validate enum values
    valid_statuses = ["open", "in_progress", "blocked", "fixed", "wont_fix"]
    if status not in valid_statuses:
        raise ValueError(f"status must be one of {valid_statuses}")
    
    valid_severities = ["low", "medium", "high", "critical"]
    if severity not in valid_severities:
        raise ValueError(f"severity must be one of {valid_severities}")
    
    ims = _ims_client()
    properties: Dict[str, Any] = {
        "project_id": project_id,
        "symptoms": symptoms,
        "status": status,
        "severity": severity,
    }
    if root_cause:
        properties["root_cause"] = root_cause
    if fix:
        properties["fix"] = fix
    if primary_file:
        properties["primary_file"] = primary_file
    if line_hint is not None:
        properties["line_hint"] = line_hint
    if external_id:
        properties["external_id"] = external_id
    if external_system:
        properties["external_system"] = external_system
    if tags:
        properties["tags"] = tags
    
    node_id = ims.graph.create_node("Bug", properties)
    return node_id


@mcp.tool("graph_create_feature")
def ims_graph_create_feature(
    project_id: str,
    description: str,
    status: str = "planned",
    priority: str = "medium",
    requirements: Optional[List[str]] = None,
    file_path: Optional[str] = None,
    line_hint: Optional[int] = None,
    external_id: Optional[str] = None,
    external_system: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> str:
    """Create a Feature node in the ontology graph.
    
    Use this to track features/capabilities to be implemented.
    
    Args:
        project_id: Project identifier
        description: What to build (min 10 chars)
        status: Feature lifecycle state (planned, in_progress, completed, cancelled)
        priority: Implementation priority (low, medium, high, critical)
        requirements: Functional requirements
        file_path: Primary file to modify
        line_hint: Where to start work
        external_id: Link to external task (e.g., GitHub Issue)
        external_system: External system type
        tags: Categorization tags
    
    Returns:
        The UUID of the created Feature node
    
    Example:
        feature_id = ims_graph_create_feature(
            project_id="my-app",
            description="Add OAuth 2.0 authentication",
            status="planned",
            priority="high",
            requirements=["Support Google OAuth", "Support GitHub OAuth"],
            file_path="auth/oauth.py",
            tags=["auth", "oauth"]
        )
    """
    # Validate project_id
    if not project_id or not isinstance(project_id, str):
        raise ValueError("project_id must be a non-empty string")
    if not project_id.strip():
        raise ValueError("project_id cannot be empty or whitespace only")
    
    # Validate required field lengths
    if len(description.strip()) < 10:
        raise ValueError("description must be at least 10 characters")
    
    # Validate enum values
    valid_statuses = ["planned", "in_progress", "completed", "cancelled"]
    if status not in valid_statuses:
        raise ValueError(f"status must be one of {valid_statuses}")
    
    valid_priorities = ["low", "medium", "high", "critical"]
    if priority not in valid_priorities:
        raise ValueError(f"priority must be one of {valid_priorities}")
    
    ims = _ims_client()
    properties: Dict[str, Any] = {
        "project_id": project_id,
        "description": description,
        "status": status,
        "priority": priority,
    }
    if requirements:
        properties["requirements"] = requirements
    if file_path:
        properties["file_path"] = file_path
    if line_hint is not None:
        properties["line_hint"] = line_hint
    if external_id:
        properties["external_id"] = external_id
    if external_system:
        properties["external_system"] = external_system
    if tags:
        properties["tags"] = tags
    
    node_id = ims.graph.create_node("Feature", properties)
    return node_id


@mcp.tool("graph_create_component")
def ims_graph_create_component(
    project_id: str,
    name: str,
    description: Optional[str] = None,
    interface: Optional[str] = None,
    responsibilities: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
) -> str:
    """Create a Component node in the ontology graph.
    
    Use this to represent system components (services, modules, packages).
    
    Args:
        project_id: Project identifier
        name: Component identifier (alphanumeric + underscore/dash)
        description: What it does
        interface: Public API/contract
        responsibilities: What it's responsible for
        tags: Categorization tags
    
    Returns:
        The UUID of the created Component node
    
    Example:
        component_id = ims_graph_create_component(
            project_id="my-app",
            name="AuthService",
            description="Handles user authentication and session management",
            interface="POST /auth/login, POST /auth/logout, GET /auth/session",
            responsibilities=["JWT token generation", "Session validation"],
            tags=["service", "auth"]
        )
    """
    # Validate project_id
    if not project_id or not isinstance(project_id, str):
        raise ValueError("project_id must be a non-empty string")
    if not project_id.strip():
        raise ValueError("project_id cannot be empty or whitespace only")
    
    # Validate name format (alphanumeric + underscore/dash)
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        raise ValueError("name must contain only alphanumeric characters, underscores, and dashes")
    
    ims = _ims_client()
    properties: Dict[str, Any] = {
        "project_id": project_id,
        "name": name,
    }
    if description:
        properties["description"] = description
    if interface:
        properties["interface"] = interface
    if responsibilities:
        properties["responsibilities"] = responsibilities
    if tags:
        properties["tags"] = tags
    
    node_id = ims.graph.create_node("Component", properties)
    return node_id


@mcp.tool("graph_create_relationship")
def ims_graph_create_relationship(
    from_id: str,
    rel_type: str,
    to_id: str,
    properties: Optional[Dict[str, Any]] = None,
) -> bool:
    """Create a relationship between two nodes in the ontology graph.
    
    Use this to establish semantic links between entities.
    
    Args:
        from_id: Source node UUID
        rel_type: Relationship type (implements, blocks, affects, depends_on,
                  supersedes, fixed_by, worked_on)
        to_id: Target node UUID
        properties: Optional relationship properties
    
    Returns:
        True if relationship created successfully
    
    Relationship semantics:
        - implements: Feature implements Decision
        - blocks: Bug/Feature blocks Feature/Bug
        - affects: Decision affects Component
        - depends_on: Component/Feature depends on Component/Decision
        - supersedes: Decision supersedes Decision (acyclic)
        - fixed_by: Bug fixed by Decision
        - worked_on: Session worked on Feature/Bug/Component
    
    Example:
        # Link feature to decision
        ims_graph_create_relationship(
            from_id=feature_id,
            rel_type="implements",
            to_id=decision_id
        )
        
        # Link bug to feature (blocking)
        ims_graph_create_relationship(
            from_id=bug_id,
            rel_type="blocks",
            to_id=feature_id
        )
    """
    # Validate relationship type
    valid_rel_types = [
        "implements",
        "blocks",
        "affects",
        "depends_on",
        "supersedes",
        "fixed_by",
        "worked_on",
    ]
    if rel_type not in valid_rel_types:
        raise ValueError(f"rel_type must be one of {valid_rel_types}")
    
    ims = _ims_client()
    success = ims.graph.create_relationship(from_id, rel_type, to_id, properties)
    return success


# ---------------------------------------------------------------------------
# Analysis Query Tools (Task 3.1)
# ---------------------------------------------------------------------------


@mcp.tool("graph_impact_analysis")
def ims_graph_impact_analysis(
    entity_id: str,
    entity_type: str,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze the impact of changing an entity.
    
    For Decisions: What components does this decision affect?
    For Components: What's the downstream impact (who depends on this)?
    
    Args:
        entity_id: Node UUID to analyze
        entity_type: Type of entity ("Decision" or "Component")
        project_id: Optional project filter
    
    Returns:
        Dict with affected entities and relationship details
    
    Example:
        # What components are affected by this decision?
        impact = ims_graph_impact_analysis(
            entity_id=decision_id,
            entity_type="Decision"
        )
        # Returns: {"results": [{"component": "AuthService", "description": "..."}]}
    """
    # Validate entity_type
    valid_types = ["Decision", "Component"]
    if entity_type not in valid_types:
        raise ValueError(f"entity_type must be one of {valid_types}")
    
    ims = _ims_client()
    result = ims.graph.impact_analysis(entity_id, entity_type)
    return result


@mcp.tool("graph_blocking_analysis")
def ims_graph_blocking_analysis(
    feature_id: str,
) -> Dict[str, Any]:
    """Find what bugs are blocking a feature.
    
    Returns open bugs that must be fixed before feature can be completed.
    
    Args:
        feature_id: Feature node UUID
    
    Returns:
        Dict with blocking bugs, sorted by severity
    
    Example:
        blockers = ims_graph_blocking_analysis(feature_id)
        # Returns: {"results": [{"symptoms": "...", "severity": "high", "status": "open"}]}
    """
    ims = _ims_client()
    result = ims.graph.blocking_analysis(feature_id)
    return result


@mcp.tool("graph_architectural_drift")
def ims_graph_architectural_drift(
    project_id: str,
) -> Dict[str, Any]:
    """Detect components following superseded decisions.
    
    Finds architectural drift where components follow old decisions that
    have been superseded by newer ones.
    
    Args:
        project_id: Project to analyze
    
    Returns:
        Dict with drifted components and decision evolution
    
    Example:
        drift = ims_graph_architectural_drift("my-app")
        # Returns: {"results": [{"component": "SessionStore", 
        #           "currently_follows": "File-based sessions",
        #           "should_follow": "Redis sessions"}]}
    """
    ims = _ims_client()
    result = ims.graph.architectural_drift(project_id)
    return result


@mcp.tool("graph_lookup_patterns")
def ims_graph_lookup_patterns(
    component_name: str,
    domain: Optional[str] = None,
) -> Dict[str, Any]:
    """Find patterns applicable to a component.
    
    Returns promoted patterns (from corrections) that apply to the component.
    
    Args:
        component_name: Component to find patterns for
        domain: Optional domain filter (e.g., "python", "auth")
    
    Returns:
        Dict with applicable patterns and confidence scores
    
    Example:
        patterns = ims_graph_lookup_patterns("AuthService", domain="auth")
        # Returns: {"results": [{"description": "Always use rate limiting", 
        #           "confidence": 1.0, "usage_count": 15}]}
    """
    ims = _ims_client()
    result = ims.graph.lookup_patterns(component_name, domain)
    return result


# ---------------------------------------------------------------------------
# Self-Improving Tools (Task 3.2)
# ---------------------------------------------------------------------------


@mcp.tool("graph_corrections_ready")
def ims_graph_corrections_ready(
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Find corrections ready to be promoted to patterns.
    
    Corrections with 3+ uses that haven't been confirmed yet.
    
    Args:
        project_id: Optional project filter
    
    Returns:
        Dict with corrections ready for promotion
    
    Example:
        ready = ims_graph_corrections_ready("my-app")
        # Returns: {"results": [{"text": "Use strict mode", "usage_count": 5}]}
    """
    ims = _ims_client()
    result = ims.graph.corrections_ready(project_id)
    return result


@mcp.tool("graph_promote_correction")
def ims_graph_promote_correction(
    correction_id: str,
) -> Dict[str, Any]:
    """Promote a correction to a pattern.
    
    Creates a Pattern node from the Correction and establishes BECOMES relationship.
    
    Args:
        correction_id: Correction node UUID to promote
    
    Returns:
        Dict with newly created Pattern node
    
    Example:
        pattern = ims_graph_promote_correction(correction_id)
        # Returns: {"pattern": {"description": "...", "confidence": 1.0}}
    """
    ims = _ims_client()
    result = ims.graph.promote_correction(correction_id)
    return result


if __name__ == "__main__":
    # For now, run on stdio so MCP clients can spawn this as a subprocess.
    # Later we can switch to or add streamable HTTP transport if desired.
    mcp.run()
