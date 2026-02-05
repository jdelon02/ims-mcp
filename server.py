"""MCP server for the Integrated Memory System (IMS).

This uses the official Model Context Protocol Python SDK
(https://github.com/modelcontextprotocol/python-sdk) and delegates all
operations to the IMS HTTP backend via `IMSClient` from the
integrated-memory-system project.

Initially we expose three tool groups:
- ims.context-rag   → /context/search
- ims.session-memory → /sessions/*
- ims.memory-core   → /memories/*
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import MCPServer

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

# Allow importing IMSClient from the integrated-memory-system project without
# requiring it to be installed as a package. We assume the repo is checked out
# alongside this ims-mcp project under ../skills/integrated-memory-system.
_IMS_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
    / "skills"
    / "integrated-memory-system"
)
if _IMS_ROOT.exists() and str(_IMS_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMS_ROOT))

try:  # type: ignore[import]
    from app.ims_client import IMSClient
except Exception as exc:  # pragma: no cover - environment specific
    raise RuntimeError(
        "Failed to import IMSClient from integrated-memory-system. "
        "Ensure the IMS repo is checked out at ../skills/integrated-memory-system "
        "relative to this ims-mcp project."
    ) from exc


def _ims_client() -> IMSClient:
    """Construct an IMSClient using IMS_BASE_URL if set.

    This keeps configuration in one place and ensures all tools share the
    same base URL / timeout.
    """

    base_url = os.getenv("IMS_BASE_URL", "http://localhost:8000").rstrip("/")
    timeout = float(os.getenv("IMS_HTTP_TIMEOUT", "5.0"))
    client_name = os.getenv("IMS_CLIENT_NAME", "ims-mcp")
    return IMSClient(base_url=base_url, timeout=timeout, client_name=client_name)


# This name is what MCP clients will see.
mcp = MCPServer("IMS MCP")


# ---------------------------------------------------------------------------
# ims.context-rag tools
# ---------------------------------------------------------------------------

@mcp.tool("ims.context-rag.context_search")
def ims_context_search(
    project_id: str,
    query: str,
    sources: Optional[List[str]] = None,
    per_source_limits: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Unified context search across code, docs, and memories for a project.

    This is a thin wrapper over the IMS `/context/search` endpoint.
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

@mcp.tool("ims.memory-core.store_memory")
def ims_store_memory(
    project_id: str,
    text: str,
    kind: str,
    tags: Optional[List[str]] = None,
    importance: Optional[float] = None,
) -> Dict[str, Any]:
    """Store a long-term memory item for a project via /memories/store."""

    ims = _ims_client()
    return ims.memory_core.store_memory(
        project_id=project_id,
        text=text,
        kind=kind,
        tags=tags,
        importance=importance,
    )


@mcp.tool("ims.memory-core.find_memories")
def ims_find_memories(
    project_id: str,
    query: str,
    kinds: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search long-term memories for a project via /memories/search."""

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

@mcp.tool("ims.session-memory.auto_session")
def ims_auto_session(
    project_id: str,
    user_message: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """High-level helper to either resume or create a session.

    Thin wrapper over `/sessions/auto`.
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


@mcp.tool("ims.session-memory.continue_session")
def ims_continue_session(
    project_id: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
    initial_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve or create a concrete session for a tuple.

    Wrapper over `/sessions/continue` via SessionMemoryClient.
    """

    ims = _ims_client()
    return ims.session_memory.continue_session(
        project_id=project_id,
        user_id=user_id,
        agent_id=agent_id,
        task_id=task_id,
        initial_state=initial_state,
    )


@mcp.tool("ims.session-memory.wrap_session")
def ims_wrap_session(
    project_id: str,
    state: Dict[str, Any],
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist an updated SessionState snapshot via `/sessions/wrap`."""

    ims = _ims_client()
    return ims.session_memory.wrap_session(
        project_id=project_id,
        state=state,
        user_id=user_id,
        agent_id=agent_id,
        task_id=task_id,
    )


@mcp.tool("ims.session-memory.list_open_sessions")
def ims_list_open_sessions(
    project_id: str,
    user_id: Optional[str] = None,
    only_open: bool = True,
) -> Dict[str, Any]:
    """List open sessions for a given (project_id, user_id) pair.

    Wrapper over `/sessions/list_open`.
    """

    ims = _ims_client()
    with ims.session_memory._client("session-memory") as client:  # type: ignore[attr-defined]
        payload: Dict[str, Any] = {"project_id": project_id, "only_open": only_open}
        if user_id is not None:
            payload["user_id"] = user_id
        resp = client.post("/sessions/list_open", json=payload)
        resp.raise_for_status()
        return resp.json()


@mcp.tool("ims.session-memory.resume_session")
def ims_resume_session(session_id: str) -> Dict[str, Any]:
    """Explicitly resume a session by session_id via `/sessions/resume`."""

    ims = _ims_client()
    with ims.session_memory._client("session-memory") as client:  # type: ignore[attr-defined]
        resp = client.post("/sessions/resume", json={"session_id": session_id})
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    # For now, run on stdio so MCP clients can spawn this as a subprocess.
    # Later we can switch to or add streamable HTTP transport if desired.
    mcp.run()
