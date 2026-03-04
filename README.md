# IMS MCP Server

MCP server that exposes the Integrated Memory System (IMS) as tools via the
[Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk).

It wraps the existing IMS HTTP backend (session-memory, memory-core,
context-rag) and makes those capabilities available to MCP-aware clients
(e.g. mcphub, Warp, VS Code, LibreChat).

## Prerequisites

- Python 3.10+
- An IMS backend running somewhere reachable (FastAPI/Uvicorn service), e.g.:
  - `http://localhost:8000`, or
  - `http://ims.delongpa.com`

That's it! The MCP server includes all necessary client code to communicate
with the IMS backend.

## Installation (venv + pip)

From the `ims-mcp` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

This installs the MCP Python SDK and required dependencies (httpx).

## Configuration

The MCP server talks to IMS via environment variables. These can be provided
in three ways (in order of **increasing** precedence):

1. A local `.env` file in the project root (or a path specified by
   `IMS_ENV_FILE`)
2. The process environment (e.g. exported variables in your shell)
3. Environment variables set by the MCP host (e.g. mcphub `env` block)

Supported variables:

- `IMS_BASE_URL` (optional, default `https://ims.delongpa.com`)
  - Base URL of the IMS HTTP service (override for local dev, e.g. `http://localhost:8000`).
- `IMS_HTTP_TIMEOUT` (optional, default `5.0` seconds)
- `IMS_CLIENT_NAME` (optional, default `"ims-mcp"`)
- `IMS_VERIFY_SSL` (optional, default `true`)
  - Set to `false` only for local/dev environments with self-signed certs.
- `IMS_ENV_FILE` (optional, default `.env`)
  - If set, points to a `.env`-style file to load before reading other vars.
- `IMS_HEALTH_PROJECT_ID` (optional, default `ims-mcp`)
  - Project id used by the `ims://health` resource when probing read endpoints.

### Using a .env file (local development)

Create a file named `.env` next to `server.py` (only needed if you want to override defaults, e.g. local dev):

```env
IMS_BASE_URL=http://localhost:8000
IMS_HTTP_TIMEOUT=5.0
IMS_CLIENT_NAME=ims-mcp
```

You can override the file name/path with `IMS_ENV_FILE` if needed.

### Setting variables directly

Example using exported variables:

```bash
export IMS_BASE_URL="http://ims.delongpa.com"
export IMS_HTTP_TIMEOUT="5.0"
export IMS_CLIENT_NAME="ims-mcp"
export IMS_VERIFY_SSL="true"
```

## Running the MCP server locally

With the venv activated (and optionally `IMS_BASE_URL` set):

```bash
source .venv/bin/activate
# Optional override for local dev:
# export IMS_BASE_URL="http://localhost:8000"
python server.py
```

The server runs over stdio, which is what MCP clients expect when they spawn
it as a subprocess.

## mcphub configuration example

To use this server from mcphub on a host where you cloned this repo to
`/opt/mcps/ims-mcp` and created the venv as above, add an entry like:

```json
"IMS-MCP": {
  "type": "stdio",
  "command": "/opt/mcps/ims-mcp/.venv/bin/python",
  "args": [
    "/opt/mcps/ims-mcp/server.py"
  ],
  "env": {
    "IMS_BASE_URL": "http://ims.delongpa.com"
  }
}
```

Adjust paths and `IMS_BASE_URL` to match your environment.

## Exposed tools

The MCP server exposes the following tools for interacting with IMS capabilities:

### Context Retrieval
- `ims.context-rag.context_search`
  - Unified search across code, docs, and memories

### Docs Indexing (Meilisearch)
- `docs_index_directory`
  - Index a directory of *text* files (docs + code + config) into Meilisearch `project_docs` (chunked by default)
  - Uses `IMS_MEILI_URL` / `IMS_MEILI_API_KEY` and stores `user_id` (from `IMS_USER_ID` or OS username)
  - Supports optional path-based filtering:
    - `include_globs`: only include files matching at least one glob (e.g. `**/*-meta.xml` for Salesforce metadata)
    - `exclude_globs`: exclude files matching any glob
    - `no_default_excludes`: disable built-in excludes (e.g. `.env*`, lockfiles, `*.min.js`)

### Long-Term Memory
- `ims.memory-core.store_memory`
  - Store decisions, issues, and facts
- `ims.memory-core.find_memories`
  - Search stored memories

### Session State
- `ims.session-memory.auto_session`
  - Smart helper to resume or create sessions
- `ims.session-memory.resolve_session`
  - Hook-aware resolver that resumes/creates a session and binds `hook_session_id` into session metadata for strict session gating
- `ims.session-memory.get_bound_session`
  - Lookup helper to verify whether a `hook_session_id` is already bound to an open IMS session for a project
- `ims.session-memory.continue_session`
  - Resolve or create session by (project, user, agent, task) tuple
- `ims.session-memory.checkpoint_session`
  - Persist session state mid-burst (save progress without implying pause/hand-off)
- `ims.session-memory.wrap_session`
  - Persist updated session state at true boundaries (pause/hand-off/finish)
- `ims.session-memory.list_open_sessions`
  - List available sessions
- `ims.session-memory.resume_session`
  - Resume specific session by ID

Each tool includes comprehensive documentation in its docstring. For the complete
IMS protocol and usage guidelines, see `AGENTS.md`.

## Exposed resources

The MCP server also exposes read-only resources for inspection/discovery:

### Health and capabilities
- `ims://health`
  - Runtime health snapshot for `session-memory`, `memory-core`, and `context-rag` reachability checks.
- `ims://capabilities`
  - Enumerates server capabilities, including tool/resource counts and discoverable tool/resource metadata.

### Session snapshots
- `ims://sessions/{project_id}/open`
  - Snapshot of open sessions for a project, using inferred user context from the backend.
- `ims://sessions/{project_id}/{user_id}/open`
  - Snapshot of open sessions for an explicit project and user.

## IMS backend changes (context-rag) to take advantage of new docs semantics

The `docs_index_directory` tool (and the underlying chunking/indexing logic) now writes richer per-chunk metadata into Meilisearch documents:

- `snippet` (short preview)
- `path` (relative path)
- `ext` (file extension without dot)
- `tags` (simple tags derived from path/extension)
- `user_id` (owner)

However, the IMS backend’s **context-rag** service (the thing behind `POST /context/search`) must be updated to *use* these fields during docs retrieval. Concretely, to leverage the new semantics you’ll typically want to update the IMS backend to:

1. Return better previews for docs hits
   - Prefer `snippet` from Meilisearch instead of returning the entire `content` chunk as the hit snippet.
   - Keep `content` available for grounding (either return it in metadata or as a separate field), but avoid flooding the prompt/UI.

2. Support docs filtering controls (ext/path/tags)
   - Extend the docs portion of the `/context/search` request to accept optional filters such as:
     - `ext`: allowlist (e.g. `["md","txt"]` or `["cls","trigger"]` for Apex)
     - `path_prefix`: e.g. `"docs/"`
     - `tags`: e.g. `["terraform","yaml"]`
   - Map these to Meilisearch `filter` expressions, relying on `path`, `ext`, and `tags` being configured as filterable attributes.

3. Handle Salesforce metadata patterns intentionally
   - Many Salesforce repos store verbose metadata as `**/*-meta.xml`. The indexer can include these using include globs, but the retrieval layer may want to:
     - de-prioritize or exclude `*-meta.xml` by default, unless the query suggests metadata is needed, or
     - apply `path`/`tags` conventions to target metadata vs source.

4. Guard relevance when doc counts increase
   - Chunking + indexing more file types increases the number of Meilisearch documents substantially.
   - Consider a light post-processing step on docs hits such as:
     - dedupe results by `path` (keep best scoring chunk per file), and/or
     - cap the number of unique `path` values to keep context diverse.

5. Decide on ownership / multi-user scoping
   - The indexer stores `user_id`. If you want per-user isolation for docs retrieval, the IMS backend should optionally filter by `user_id` when present.
   - If you want project-shared docs, keep filtering project-only.

If you want to keep the IMS backend interface stable, the smallest useful change is #1 (use `snippet`) plus a single optional `ext` filter for the docs retrieval portion.
