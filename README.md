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
- The `integrated-memory-system` repo checked out on disk in this layout
  (relative to this project):

```text
<some-parent-dir>/
  skills/
    integrated-memory-system/   # IMS FastAPI project (provides IMSClient)
  ims-mcp/                      # this repo
```

`server.py` imports `IMSClient` from `skills/integrated-memory-system/app/ims_client.py`
using a relative path; if your layout is different, adjust `server.py` accordingly.

## Installation (venv + pip)

From the `ims-mcp` directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

This installs the official MCP Python SDK (`mcp[cli]`).

## Configuration

The MCP server talks to IMS via environment variables:

- `IMS_BASE_URL` (required)
  - Base URL of the IMS HTTP service, e.g. `http://localhost:8000` or
    `https://ims.delongpa.com`.
- `IMS_HTTP_TIMEOUT` (optional, default `5.0` seconds)
- `IMS_CLIENT_NAME` (optional, default `"ims-mcp"`)

Example:

```bash
export IMS_BASE_URL="http://ims.delongpa.com"
export IMS_HTTP_TIMEOUT="5.0"
export IMS_CLIENT_NAME="ims-mcp"
```

## Running the MCP server locally

With the venv activated and `IMS_BASE_URL` set:

```bash
. .venv/bin/activate
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

The MCP server exposes the following tools (namespaces follow the IMS
service names):

- `ims.context-rag.context_search`
  - Wrapper over `POST /context/search`.
- `ims.memory-core.store_memory`
  - Wrapper over `POST /memories/store`.
- `ims.memory-core.find_memories`
  - Wrapper over `POST /memories/search`.
- `ims.session-memory.auto_session`
  - Wrapper over `POST /sessions/auto`.
- `ims.session-memory.continue_session`
  - Wrapper over `POST /sessions/continue`.
- `ims.session-memory.wrap_session`
  - Wrapper over `POST /sessions/wrap`.
- `ims.session-memory.list_open_sessions`
  - Wrapper over `POST /sessions/list_open`.
- `ims.session-memory.resume_session`
  - Wrapper over `POST /sessions/resume`.

For detailed behavior of these endpoints, see `spec/API_ENDPOINTS.md` in the
`integrated-memory-system` repo and `AGENTS.md` in this repo for the IMS
agent protocol.
