"""Chunked Meilisearch docs indexing utilities.

This mirrors the blueprint implementation in the sibling project
`../vectorizeme/ims_meili_index_docs.py`, but is packaged for use inside the
ims-mcp server so it can expose an MCP tool for indexing docs.

Environment variables:
- IMS_MEILI_URL (required)
- IMS_MEILI_API_KEY (optional, but typically required)
- IMS_USER_ID (optional; used as default user_id)
"""

from __future__ import annotations

import getpass
import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

DEFAULT_INDEX_UID = "project_docs"

DEFAULT_EXTS: set[str] = {
    ".md",
    ".markdown",
    ".mdx",
    ".txt",
    ".rst",
    ".adoc",
    ".org",
}

DEFAULT_PRUNE_DIRS: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
}

DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_BATCH_SIZE = 100
DEFAULT_CHUNK_MAX_CHARS = 4000
DEFAULT_SNIPPET_CHARS = 400


class MeiliDocsIndexError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocRecord:
    id: str
    project_id: str
    user_id: str
    title: str
    chunk_title: str
    path: str
    chunk_index: int
    content: str
    snippet: str
    tags: List[str]
    ext: str
    bytes: int
    mtime: float

    def to_meili(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "title": self.title,
            "chunk_title": self.chunk_title,
            "path": self.path,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "snippet": self.snippet,
            "tags": self.tags,
            "ext": self.ext,
            "bytes": self.bytes,
            "mtime": self.mtime,
        }


def _env(name: str) -> Optional[str]:
    val = os.getenv(name)
    if val is None:
        return None
    val = val.strip()
    return val or None


def default_user_id() -> str:
    return _env("IMS_USER_ID") or getpass.getuser() or "default"


def _meili_base_url() -> str:
    url = _env("IMS_MEILI_URL")
    if not url:
        raise MeiliDocsIndexError("IMS_MEILI_URL is not set")
    return url.rstrip("/")


def _meili_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": "ims-mcp/meili-docs-indexer",
    }
    api_key = _env("IMS_MEILI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _detect_title(text: str, *, fallback: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip() or fallback
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s[:200]
    return fallback


def _tags_for_path(rel_path: Path) -> List[str]:
    tags: List[str] = []
    parts = rel_path.parts
    if len(parts) >= 2:
        tags.append(parts[0])
    ext = rel_path.suffix.lower().lstrip(".")
    if ext:
        tags.append(ext)
    if not tags:
        tags.append("docs")

    seen: set[str] = set()
    out: List[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _doc_id(project_id: str, user_id: str, rel_path: str, chunk_index: int) -> str:
    h = hashlib.sha1(
        f"{project_id}:{user_id}:{rel_path}:{chunk_index}".encode("utf-8")
    ).hexdigest()  # nosec B303 - non-crypto use
    return h


def _make_snippet(text: str, snippet_chars: int) -> str:
    if snippet_chars <= 0:
        return ""
    s = re.sub(r"\s+", " ", text.strip())
    if len(s) <= snippet_chars:
        return s
    return s[:snippet_chars].rstrip() + "…"


def _split_large_block(block: str, max_chars: int) -> List[str]:
    if max_chars <= 0:
        return [block]
    if len(block) <= max_chars:
        return [block]

    out: List[str] = []
    start = 0
    while start < len(block):
        end = min(len(block), start + max_chars)
        nl = block.rfind("\n", start, end)
        if nl > start + 200:
            end = nl
        out.append(block[start:end].strip("\n"))
        start = end
    return [x for x in out if x.strip()]


def _chunk_by_paragraphs(text: str, max_chars: int) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return []

    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur, cur_len
        if not cur:
            return
        chunks.append("\n\n".join(cur).strip())
        cur = []
        cur_len = 0

    for p in paras:
        if max_chars > 0 and len(p) > max_chars:
            flush()
            chunks.extend(_split_large_block(p, max_chars))
            continue

        add_len = len(p) + (2 if cur else 0)
        if max_chars > 0 and cur and (cur_len + add_len) > max_chars:
            flush()

        cur.append(p)
        cur_len += add_len

    flush()
    return chunks


def _chunk_markdown(text: str, max_chars: int) -> List[Tuple[str, str]]:
    """Return markdown chunks as (chunk_title, chunk_text)."""

    lines = text.splitlines()
    header_re = re.compile(r"^(#{1,6})\s+(.*)\s*$")

    sections: List[Tuple[Optional[str], List[str]]] = []
    current_title: Optional[str] = None
    current_lines: List[str] = []

    def push_section() -> None:
        nonlocal current_title, current_lines
        if current_lines:
            sections.append((current_title, current_lines))
        current_lines = []

    for line in lines:
        m = header_re.match(line)
        if m:
            push_section()
            current_title = m.group(2).strip() or None
            current_lines = [line]
        else:
            current_lines.append(line)

    push_section()

    chunks: List[Tuple[str, str]] = []
    for sec_title, sec_lines in sections:
        sec_text = "\n".join(sec_lines).strip()
        if not sec_text:
            continue

        if max_chars <= 0 or len(sec_text) <= max_chars:
            chunks.append((sec_title or "(untitled)", sec_text))
            continue

        # Oversized section: chunk it by paragraphs, but repeat the section header
        # line for context.
        first = sec_lines[0] if sec_lines else ""
        rest = "\n".join(sec_lines[1:]).strip()
        sub_chunks = _chunk_by_paragraphs(rest, max_chars=max(1, max_chars - len(first) - 2))
        if not sub_chunks:
            chunks.append((sec_title or "(untitled)", sec_text))
            continue

        for i, sub in enumerate(sub_chunks, start=1):
            title = sec_title or "(untitled)"
            chunks.append((f"{title} ({i})", (first + "\n\n" + sub).strip()))

    return chunks


def _walk_files(root: Path, *, prune_dirs: set[str]) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in prune_dirs and not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            yield Path(dirpath) / name


def collect_docs(
    *,
    root: Path,
    project_id: str,
    user_id: str,
    exts: set[str],
    max_bytes: int,
    prune_dirs: set[str],
    chunking: bool,
    chunk_max_chars: int,
    snippet_chars: int,
) -> Tuple[List[DocRecord], Dict[str, int]]:
    records: List[DocRecord] = []
    stats = {
        "seen": 0,
        "files_kept": 0,
        "chunks_kept": 0,
        "skipped_ext": 0,
        "skipped_large": 0,
        "skipped_read": 0,
    }

    for path in _walk_files(root, prune_dirs=prune_dirs):
        stats["seen"] += 1

        ext = path.suffix.lower()
        if ext not in exts:
            stats["skipped_ext"] += 1
            continue

        try:
            st = path.stat()
        except OSError:
            stats["skipped_read"] += 1
            continue

        if st.st_size > max_bytes:
            stats["skipped_large"] += 1
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stats["skipped_read"] += 1
            continue

        rel_path = str(path.relative_to(root))
        file_title = _detect_title(text, fallback=path.name)
        tags = _tags_for_path(Path(rel_path))

        if chunking:
            if ext in {".md", ".markdown", ".mdx"}:
                chunk_pairs = _chunk_markdown(text, max_chars=chunk_max_chars)
                chunks = [c for _, c in chunk_pairs]
                chunk_titles = [t for t, _ in chunk_pairs]
            else:
                chunks = _chunk_by_paragraphs(text, max_chars=chunk_max_chars)
                chunk_titles = [file_title for _ in chunks]
        else:
            chunks = [text]
            chunk_titles = [file_title]

        if not chunks:
            continue

        stats["files_kept"] += 1

        for idx, chunk_text in enumerate(chunks):
            chunk_title = chunk_titles[idx] if idx < len(chunk_titles) else file_title
            records.append(
                DocRecord(
                    id=_doc_id(project_id, user_id, rel_path, idx),
                    project_id=project_id,
                    user_id=user_id,
                    title=file_title,
                    chunk_title=chunk_title,
                    path=rel_path,
                    chunk_index=idx,
                    content=chunk_text,
                    snippet=_make_snippet(chunk_text, snippet_chars=snippet_chars),
                    tags=tags,
                    ext=ext.lstrip("."),
                    bytes=int(st.st_size),
                    mtime=float(st.st_mtime),
                )
            )
            stats["chunks_kept"] += 1

    return records, stats


def _chunked(items: Sequence[DocRecord], chunk_size: int) -> Iterable[List[DocRecord]]:
    for i in range(0, len(items), chunk_size):
        yield list(items[i : i + chunk_size])


def ensure_index(*, index_uid: str = DEFAULT_INDEX_UID) -> None:
    base = _meili_base_url()
    headers = _meili_headers()

    with httpx.Client(base_url=base, headers=headers, timeout=10.0) as client:
        resp = client.post("/indexes", json={"uid": index_uid, "primaryKey": "id"})
        if resp.status_code not in (200, 201, 202, 204, 409):
            raise MeiliDocsIndexError(f"Failed to ensure index {index_uid}: {resp.status_code} {resp.text}")

        # Best-effort: filterable attributes for scoping.
        try:
            resp2 = client.put(
                f"/indexes/{index_uid}/settings/filterable-attributes",
                json=["project_id", "user_id", "tags", "path", "ext"],
            )
            _ = resp2  # ignore failures
        except Exception:
            pass


def upload_docs(
    *,
    records: Sequence[DocRecord],
    index_uid: str = DEFAULT_INDEX_UID,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> List[Dict[str, Any]]:
    if not records:
        return []

    base = _meili_base_url()
    headers = _meili_headers()

    tasks: List[Dict[str, Any]] = []
    with httpx.Client(base_url=base, headers=headers, timeout=30.0) as client:
        for batch in _chunked(records, batch_size):
            payload = [r.to_meili() for r in batch]
            resp = client.post(f"/indexes/{index_uid}/documents", json=payload)
            resp.raise_for_status()
            try:
                tasks.append(resp.json())
            except Exception:
                tasks.append({"status_code": resp.status_code, "text": resp.text})

    return tasks


def index_directory_docs(
    *,
    root_dir: str,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    index_uid: str = DEFAULT_INDEX_UID,
    exts: Optional[Sequence[str]] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    prune_dirs: Optional[Sequence[str]] = None,
    chunking: bool = True,
    chunk_max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Index a directory tree into Meilisearch (project_docs), optionally chunked."""

    root = Path(root_dir).expanduser().resolve()
    if not root.is_dir():
        raise MeiliDocsIndexError(f"root_dir is not a directory: {root}")

    pid = project_id or root.name
    uid = user_id or default_user_id()

    ext_set = (
        DEFAULT_EXTS
        if exts is None
        else {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}
    )
    prune = set(DEFAULT_PRUNE_DIRS) if prune_dirs is None else set(prune_dirs)

    t0 = time.time()
    records, stats = collect_docs(
        root=root,
        project_id=pid,
        user_id=uid,
        exts=ext_set,
        max_bytes=max_bytes,
        prune_dirs=prune,
        chunking=chunking,
        chunk_max_chars=chunk_max_chars,
        snippet_chars=snippet_chars,
    )

    tasks: List[Dict[str, Any]] = []
    if not dry_run:
        ensure_index(index_uid=index_uid)
        tasks = upload_docs(records=records, index_uid=index_uid, batch_size=batch_size)

    dt = time.time() - t0
    return {
        "root": str(root),
        "project_id": pid,
        "user_id": uid,
        "index_uid": index_uid,
        "chunking": bool(chunking),
        "chunk_max_chars": int(chunk_max_chars),
        "snippet_chars": int(snippet_chars),
        "exts": sorted(ext_set),
        "stats": stats,
        "dry_run": bool(dry_run),
        "elapsed_seconds": round(dt, 3),
        # keep tasks compact
        "meili_tasks": tasks[-3:],
    }
