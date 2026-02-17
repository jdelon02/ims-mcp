"""IMS client wrappers for memory-core, session-memory, and context-rag.

This module provides a small, opinionated client layer for the Integrated
Memory System (IMS). Agents and tools should prefer using these clients over
issuing raw HTTP requests to the FastAPI service.

- `MemoryCoreClient` wraps the long-term memory endpoints.
- `SessionMemoryClient` wraps the session-memory endpoints.
- `ContextRagClient` wraps the unified context search endpoint.
- `IMSClient` aggregates the three into a single convenience entrypoint.

By default, the clients talk to `IMS_BASE_URL` (env var).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import os
import getpass

import httpx


def _raise_for_status_with_body(resp: httpx.Response) -> None:
    """Raise for HTTP errors but include the response body in the exception.

    FastAPI validation failures (422) often include a useful JSON body.
    httpx.HTTPStatusError's default string is usually too terse for debugging.
    """

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = resp.text
        except Exception:  # noqa: BLE001
            body = "<unable to read response body>"

        raise httpx.HTTPStatusError(
            message=(
                f"{exc}\n"
                f"Response status: {resp.status_code}\n"
                f"Response body: {body}"
            ),
            request=exc.request,
            response=resp,
        ) from exc


def _default_base_url() -> str:
    """Return the base URL for the IMS HTTP service.

    Uses `IMS_BASE_URL` if set, otherwise defaults to `https://ims.delongpa.com`.
    """

    return os.getenv("IMS_BASE_URL", "https://ims.delongpa.com").rstrip("/")


def _default_user_id() -> str:
    """Derive a stable user_id for this environment.

    Preference order:
    - Explicit IMS_USER_ID env var (if set)
    - OS username (whoami)
    - Fallback "default"
    """

    return os.getenv("IMS_USER_ID") or getpass.getuser() or "default"


def _default_project_id() -> str:
    """Best-effort default project_id based on the current working directory.

    This mirrors the convention used in AGENT/IMS: `project_id = basename($PWD)`.
    Callers may still choose to pass an explicit project_id instead.
    """

    return os.path.basename(os.getcwd()) or "default-project"


@dataclass
class _BaseClient:
    """Base HTTP client configuration shared by IMS sub-clients."""

    base_url: str = _default_base_url()
    timeout: float = 5.0
    client_name: str = "ims_client"
    verify_ssl: bool = True

    def _headers(self, component: str) -> Dict[str, str]:
        """Build default headers, including a client identifier.

        `component` should be one of: "memory-core", "session-memory",
        "context-rag", etc.
        """

        return {
            "X-IMS-Client": f"{self.client_name}:{component}",
            "Content-Type": "application/json",
        }

    def _client(self, component: str) -> httpx.Client:
        """Create a short-lived httpx.Client for a single operation."""

        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._headers(component),
            verify=self.verify_ssl,
        )


class MemoryCoreClient(_BaseClient):
    """Client wrapper for the memory-core long-term memory service."""

    def store_memory(
        self,
        *,
        project_id: Optional[str] = None,
        text: str,
        kind: str,
        tags: Optional[List[str]] = None,
        importance: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Store a new memory via `/memories/store`.

        Returns the parsed JSON response (a MemoryOut dict).
        """

        pid = project_id or _default_project_id()
        payload: Dict[str, Any] = {
            "project_id": pid,
            "text": text,
            "kind": kind,
        }
        if tags is not None:
            payload["tags"] = tags
        if importance is not None:
            payload["importance"] = importance

        with self._client("memory-core") as client:
            resp = client.post("/memories/store", json=payload)
            _raise_for_status_with_body(resp)
            return resp.json()

    def find_memories(
        self,
        *,
        project_id: Optional[str] = None,
        query: str,
        kinds: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search memories via `/memories/search` and return a list of results."""

        pid = project_id or _default_project_id()
        payload: Dict[str, Any] = {
            "project_id": pid,
            "query": query,
            "limit": limit,
        }
        if kinds is not None:
            payload["kinds"] = kinds
        if tags is not None:
            payload["tags"] = tags

        with self._client("memory-core") as client:
            resp = client.post("/memories/search", json=payload)
            _raise_for_status_with_body(resp)
            body = resp.json()
            # Expecting shape {"results": [...]}
            return list(body.get("results", []))


class SessionMemoryClient(_BaseClient):
    """Client wrapper for the session-memory service.

    Provides high-level `continue_session`, `checkpoint_session`, and `wrap_session` helpers.
    """

    def continue_session(
        self,
        *,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resolve or create the current session for a tuple.

        Returns the parsed JSON
        `{ "status": "created" | "resumed", "session_id": str, "state": {...} }`.
        Callers typically only need `session_id` and `state`.
        """

        pid = project_id or _default_project_id()
        uid = user_id or _default_user_id()

        payload: Dict[str, Any] = {
            "project_id": pid,
            # We still send user_id so the server does not have to re-derive it.
            "user_id": uid,
        }
        if agent_id is not None:
            payload["agent_id"] = agent_id
        if task_id is not None:
            payload["task_id"] = task_id
        if initial_state is not None:
            payload["initial_state"] = initial_state

        with self._client("session-memory") as client:
            resp = client.post("/sessions/continue", json=payload)
            _raise_for_status_with_body(resp)
            return resp.json()

    def checkpoint_session(
        self,
        *,
        project_id: Optional[str] = None,
        state: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist an updated SessionState snapshot mid-burst via `/sessions/checkpoint`.

        `checkpoint` differs from `wrap` semantically:
        - checkpoint: "I'm still working; persist progress so far"
        - wrap: "I'm pausing/handing off/ending this work burst"

        Returns `{ "status": "checkpointed", "session_id": str, "state": {...} }`.
        """

        pid = project_id or _default_project_id()
        uid = user_id or state.get("user_id") or _default_user_id()

        payload: Dict[str, Any] = {
            "project_id": pid,
            "user_id": uid,
            "state": state,
        }
        if agent_id is not None:
            payload["agent_id"] = agent_id
        if task_id is not None:
            payload["task_id"] = task_id

        with self._client("session-memory") as client:
            resp = client.post("/sessions/checkpoint", json=payload)
            _raise_for_status_with_body(resp)
            return resp.json()

    def wrap_session(
        self,
        *,
        project_id: Optional[str] = None,
        state: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist an updated SessionState snapshot via `/sessions/wrap`.

        `state` should be a full SessionState dict (e.g., previously returned
        from `continue_session` and then modified by the caller).
        Returns the normalized
        `{ "status": "wrapped", "session_id": str, "state": {...} }`.
        """

        pid = project_id or _default_project_id()
        uid = user_id or state.get("user_id") or _default_user_id()

        payload: Dict[str, Any] = {
            "project_id": pid,
            "user_id": uid,
            "state": state,
        }
        if agent_id is not None:
            payload["agent_id"] = agent_id
        if task_id is not None:
            payload["task_id"] = task_id

        with self._client("session-memory") as client:
            resp = client.post("/sessions/wrap", json=payload)
            _raise_for_status_with_body(resp)
            return resp.json()


class ContextRagClient(_BaseClient):
    """Client wrapper for the context-rag unified context retrieval service."""

    def context_search(
        self,
        *,
        project_id: Optional[str] = None,
        query: str,
        sources: Optional[List[str]] = None,
        per_source_limits: Optional[Dict[str, int]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call `/context/search` and return the full JSON response.

        Response shape: `{ "results": [ContextHit, ...] }`.

        If `user_id` is provided, the server may use it to scope docs retrieval
        (Meilisearch) for per-user ownership isolation.
        """

        pid = project_id or _default_project_id()
        payload: Dict[str, Any] = {
            "project_id": pid,
            "query": query,
        }
        if sources is not None:
            payload["sources"] = sources
        if per_source_limits is not None:
            payload["per_source_limits"] = per_source_limits
        if user_id is not None:
            payload["user_id"] = user_id

        with self._client("context-rag") as client:
            resp = client.post("/context/search", json=payload)
            _raise_for_status_with_body(resp)
            return resp.json()


class ProjectRegistryClient(_BaseClient):
    """Client wrapper for project registry endpoints (project_integrations)."""

    def upsert_project(self, *, project_id: str, name: Optional[str] = None, integration: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"project_id": project_id}
        if name is not None:
            payload["name"] = name
        if integration is not None:
            payload["integration"] = integration

        with self._client("project-registry") as client:
            resp = client.post("/projects/upsert", json=payload)
            _raise_for_status_with_body(resp)
            return resp.json()

    def get_project(self, *, project_id: str) -> Dict[str, Any]:
        with self._client("project-registry") as client:
            resp = client.get(f"/projects/{project_id}")
            _raise_for_status_with_body(resp)
            return resp.json()


class TaskMemoryClient(_BaseClient):
    """Client wrapper for GitHub-backed task-memory endpoints."""

    def create_task(
        self,
        *,
        project_id: str,
        subject: str,
        description: str = "",
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        priority: str = "medium",
        file_path: Optional[str] = None,
        line_hint: Optional[int] = None,
        owner: Optional[str] = None,
        issues_github_repo: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "project_id": project_id,
            "subject": subject,
            "description": description,
            "priority": priority,
        }
        if session_id is not None:
            payload["session_id"] = session_id
        if tags is not None:
            payload["tags"] = tags
        if file_path is not None:
            payload["file_path"] = file_path
        if line_hint is not None:
            payload["line_hint"] = line_hint
        if owner is not None:
            payload["owner"] = owner
        if issues_github_repo is not None:
            payload["issues_github_repo"] = issues_github_repo

        with self._client("task-memory") as client:
            resp = client.post("/tasks/create", json=payload)
            _raise_for_status_with_body(resp)
            return resp.json()


@dataclass
class IMSClient:
    """Aggregate client exposing memory-core, session-memory, and context-rag.

    Example usage:

        ims = IMSClient()
        session = ims.session_memory.continue_session(agent_id="planner")
        memories = ims.memory_core.find_memories(query="auth decision")
        ctx = ims.context_rag.context_search(query="How is session state stored?")
    """

    base_url: str = _default_base_url()
    timeout: float = 5.0
    client_name: str = "ims_client"
    verify_ssl: bool = True

    def __post_init__(self) -> None:
        self.memory_core = MemoryCoreClient(
            base_url=self.base_url,
            timeout=self.timeout,
            client_name=self.client_name,
            verify_ssl=self.verify_ssl,
        )
        self.session_memory = SessionMemoryClient(
            base_url=self.base_url,
            timeout=self.timeout,
            client_name=self.client_name,
            verify_ssl=self.verify_ssl,
        )
        self.context_rag = ContextRagClient(
            base_url=self.base_url,
            timeout=self.timeout,
            client_name=self.client_name,
            verify_ssl=self.verify_ssl,
        )
        self.project_registry = ProjectRegistryClient(
            base_url=self.base_url,
            timeout=self.timeout,
            client_name=self.client_name,
            verify_ssl=self.verify_ssl,
        )
        self.task_memory = TaskMemoryClient(
            base_url=self.base_url,
            timeout=self.timeout,
            client_name=self.client_name,
            verify_ssl=self.verify_ssl,
        )
