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

- `IMS_BASE_URL` (required)
  - Base URL of the IMS HTTP service, e.g. `http://localhost:8000` or
    `https://ims.delongpa.com`.
- `IMS_HTTP_TIMEOUT` (optional, default `5.0` seconds)
- `IMS_CLIENT_NAME` (optional, default `"ims-mcp"`)
- `IMS_ENV_FILE` (optional, default `.env`)
  - If set, points to a `.env`-style file to load before reading other vars.

### Using a .env file (local development)

Create a file named `.env` next to `server.py`:

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
```

## Running the MCP server locally

With the venv activated and `IMS_BASE_URL` set:

```bash
source .venv/bin/activate
export IMS_BASE_URL="http://localhost:8000"  # or your IMS URL
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

### Long-Term Memory
- `ims.memory-core.store_memory`
  - Store decisions, issues, and facts
- `ims.memory-core.find_memories`
  - Search stored memories

### Session State
- `ims.session-memory.auto_session`
  - Smart helper to resume or create sessions
- `ims.session-memory.continue_session`
  - Resolve or create session by (project, user, agent, task) tuple
- `ims.session-memory.wrap_session`
  - Persist updated session state
- `ims.session-memory.list_open_sessions`
  - List available sessions
- `ims.session-memory.resume_session`
  - Resume specific session by ID

Each tool includes comprehensive documentation in its docstring. For the complete
IMS protocol and usage guidelines, see `AGENTS.md`.
