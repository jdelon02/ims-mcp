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
  - Unified search across code, docs, and memories with optional graph expansion
  - **New in Phase 4:** `expand_graph` (default: true) and `graph_depth` (default: 2) parameters
  - When `expand_graph=true`, vector search results are enriched with related entities from the ontology graph

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
  - **New in Phase 4:** Auto-creates ontology graph nodes
    - `kind="decision"` → creates Decision node in Neo4j
    - `kind="issue"` → creates Bug node in Neo4j
    - `kind="fact"`/`"note"` → memory only (no graph node)
  - Enables relationship tracking and impact analysis for decisions and bugs
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

### Graph Operations (Ontology)
- `ims.graph.create_node`
  - Create ontology nodes (Decision, Bug, Feature, Component, Correction, Reflection, Pattern, Lesson)
- `ims.graph.create_relationship`
  - Create relationships between nodes (implements, blocks, affects, etc.)
- `ims.graph.impact_analysis`
  - Find what would be affected by changes to an entity
- `ims.graph.blocking_analysis`
  - Identify bugs blocking a feature
- `ims.graph.architectural_drift`
  - Detect components following superseded decisions
- `ims.graph.lookup_patterns`
  - Find patterns applicable to a component
- `ims.graph.corrections_ready`
  - Find corrections ready for promotion to patterns
- `ims.graph.promote_correction`
  - Promote a correction to a reusable pattern

Each tool includes comprehensive documentation in its docstring. For the complete
IMS protocol and usage guidelines, see `AGENTS.md`.

## Client library usage

The `app/` directory provides client libraries for direct programmatic access to IMS:

```python
from app.ims_client import IMSClient

ims = IMSClient()

# Session management
session = ims.session_memory.continue_session(
    project_id="my-project",
    agent_id="implementer",
    task_id="add-feature"
)

# Long-term memory with automatic graph node creation
# kind="decision" automatically creates a Decision node in Neo4j
memory = ims.memory_core.store_memory(
    project_id="my-project",
    text="Use Redis for session state. Rationale: Need TTL and atomic ops.",
    kind="decision",  # Creates Decision node in graph
    tags=["architecture", "redis"],
    importance=0.9
)

# kind="issue" automatically creates a Bug node in Neo4j
ims.memory_core.store_memory(
    project_id="my-project",
    text="Auth timeout bug fixed by increasing session TTL to 1 hour",
    kind="issue",  # Creates Bug node in graph
    tags=["bug", "auth"]
)

# Context search with graph expansion (default)
results = ims.context_rag.context_search(
    project_id="my-project",
    query="How is authentication handled?",
    sources=["code", "docs", "memories"],
    expand_graph=True,  # Default: enrich with graph relationships
    graph_depth=2       # Default: traverse 2 levels deep
)

# Vector-only search (disable graph expansion)
results = ims.context_rag.context_search(
    project_id="my-project",
    query="authentication patterns",
    sources=["code"],
    expand_graph=False  # Disable graph expansion for pure vector search
)

# Graph operations (ontology)
node_id = ims.graph.create_node(
    node_type="Decision",
    properties={
        "text": "Use Redis for session state",
        "project_id": "my-project",
        "rationale": "Low latency, TTL support"
    }
)

# Create relationships
ims.graph.create_relationship(
    from_id=decision_node_id,
    rel_type="affects",
    to_id=component_node_id,
    properties={"impact": "high"}
)

# Impact analysis
impact = ims.graph.impact_analysis(
    entity_id=decision_node_id,
    entity_type="Decision"
)
```

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

## Migration Guide from Pre-Ontology IMS

If you're upgrading from a pre-ontology version of IMS, this section explains what changed and how to adapt your workflows.

### What Changed

**New capabilities added (fully backward compatible):**
- Graph operations (node creation, relationships, analysis queries)
- Enhanced `context-rag` with optional graph expansion
- Auto-graph-node creation when storing decisions/issues via `memory-core`

**No breaking changes:**
- All existing tools continue to work as before
- Existing `memory-core.store_memory` calls automatically benefit from graph node creation
- Existing `context-rag.context_search` calls automatically include graph expansion (can be disabled)

### For Existing Users

**You don't need to change anything** to keep using IMS as before. However, you can opt into new capabilities:

#### 1. Enhanced Context Search

Pre-ontology:
```python
# Pure vector similarity search
results = ims.context_rag.context_search(
    project_id="my-app",
    query="authentication flow",
    sources=["code", "docs", "memories"]
)
```

Post-ontology (default behavior, enhanced with graph relationships):
```python
# Hybrid vector + graph search (automatically enabled)
results = ims.context_rag.context_search(
    project_id="my-app",
    query="authentication flow",
    sources=["code", "docs", "memories"],
    expand_graph=True,   # Default: enriches results with related entities
    graph_depth=2        # Default: traverse 2 relationship levels
)
```

To disable graph expansion (revert to pure vector search):
```python
results = ims.context_rag.context_search(
    project_id="my-app",
    query="authentication flow",
    sources=["code"],
    expand_graph=False  # Disable graph for pure vector similarity
)
```

#### 2. Automatic Graph Node Creation

Pre-ontology:
```python
# Just stored in Postgres + Qdrant
memory_id = ims.memory_core.store_memory(
    project_id="my-app",
    text="Use Redis for session state. Rationale: Low latency, TTL support.",
    kind="decision",
    tags=["architecture", "redis"]
)
```

Post-ontology (automatic graph node, no code changes needed):
```python
# Same call, now also creates Decision node in Neo4j graph
memory_id = ims.memory_core.store_memory(
    project_id="my-app",
    text="Use Redis for session state. Rationale: Low latency, TTL support.",
    kind="decision",  # Automatically creates Decision graph node
    tags=["architecture", "redis"]
)
# Backend now creates:
# - Memory record (Postgres + Qdrant embedding) - as before
# - Decision node (Neo4j graph) - NEW, enables relationships & impact analysis
```

#### 3. New Graph Operations (Opt-In)

You can now explicitly create relationships and run analysis queries:

```python
# Create explicit relationships between entities
ims.graph.create_relationship(
    from_id=decision_node_id,
    rel_type="affects",
    to_id=component_node_id,
    properties={"impact": "high"}
)

# Run impact analysis
impact = ims.graph.impact_analysis(
    entity_id=decision_node_id,
    entity_type="Decision"
)
print(f"This decision affects {len(impact['affected_components'])} components")

# Find blocking bugs
blocking = ims.graph.blocking_analysis(feature_id="auth-2fa")
print(f"{len(blocking['blocking_bugs'])} bugs block this feature")
```

### Migration Steps

**For most users: No action required.** Your existing code continues to work and automatically benefits from graph enhancements.

**To fully leverage ontology features:**

1. **Understand auto-graph-node behavior:**
   - `kind="decision"` → creates Decision node
   - `kind="issue"` → creates Bug node
   - `kind="fact"`/`"note"` → memory only (no graph node)

2. **Review existing memories:**
   - Memories stored pre-ontology exist only in Postgres + Qdrant
   - New memories (post-ontology) also create graph nodes
   - No need to migrate old memories unless you need graph relationships for them

3. **Adopt graph operations incrementally:**
   - Start with impact analysis on new decisions
   - Add explicit relationships as you identify dependencies
   - Use blocking analysis when planning features

4. **Adjust context search if needed:**
   - If graph expansion returns too many results, reduce `graph_depth`
   - If you need pure vector search, set `expand_graph=False`

### Backward Compatibility Guarantee

- All pre-ontology tool signatures remain unchanged
- Default behavior is backward compatible with intelligent enhancements
- Graph features are additive, not replacing existing functionality
- You can disable graph features via parameters if needed

## Performance Characteristics

### Context Search (`context-rag`)

**Vector-only search (expand_graph=False):**
- Typical latency: 100-300ms (depends on Qdrant/Meilisearch cluster size)
- Scales with: number of vectors/docs, embedding size
- Best for: Fast similarity search when relationships don't matter

**Hybrid vector + graph search (expand_graph=True, default):**
- Typical latency: 200-800ms (vector search + graph traversal)
- Scales with: `graph_depth` (each level adds ~50-200ms), graph density
- Best for: Comprehensive context that includes related entities

**Recommendations:**
- For exploratory queries: Use hybrid search (default)
- For specific code lookups: Use `expand_graph=False` for speed
- Limit `graph_depth` to 1-2 for most queries (default: 2)
- Use `graph_depth=3` only for deep dependency analysis

### Memory Storage (`memory-core`)

**Pre-ontology (memory only):**
- Latency: 50-150ms (Postgres insert + Qdrant embedding)

**Post-ontology (memory + graph node):**
- Latency: 100-250ms (Postgres + Qdrant + Neo4j node creation)
- Additional ~50-100ms overhead for graph node creation
- `kind="decision"`/`"issue"` incur graph overhead
- `kind="fact"`/`"note"` remain at pre-ontology speed (no graph node)

**Recommendations:**
- The overhead is acceptable for decision/issue tracking (one-time cost)
- For high-frequency fact storage, graph creation has minimal impact (facts don't create nodes)

### Graph Operations

**Node creation:**
- Latency: 50-100ms (Neo4j write)
- Scales with: node property count, index updates

**Relationship creation:**
- Latency: 50-100ms (Neo4j relationship write)
- Scales with: relationship property count, graph density

**Analysis queries (impact, blocking, drift):**
- Latency: 100-500ms (depends on graph traversal depth and density)
- Impact analysis: Typically 150-300ms for depth 2-3
- Blocking analysis: Typically 100-200ms (usually shallow graph)
- Architectural drift: Typically 200-500ms (scans superseded decisions)

**Recommendations:**
- Use analysis queries sparingly (not in tight loops)
- Cache analysis results when possible (changes infrequently)
- Limit traversal depth when results are large

### Scaling Considerations

**Vector stores (Qdrant):**
- Handles millions of vectors efficiently
- Use collections per project for isolation
- Consider sharding for very large codebases

**Graph database (Neo4j):**
- Handles millions of nodes/relationships
- Performance degrades with very dense graphs (thousands of edges per node)
- Use relationship types strategically to enable filtered traversals
- Index frequently-queried properties (project_id, node_type)

**Text search (Meilisearch):**
- Handles millions of documents
- Chunk documents to ~500-1000 tokens for best relevance
- Use filterable attributes (ext, tags, path) to reduce search space

## Troubleshooting

### Graph Operations Failing

**Symptom:** `ims.graph.create_node()` returns 500 error

**Likely causes:**
1. Neo4j backend not accessible from IMS backend
2. Ontology schema not initialized
3. Invalid node_type or missing required properties

**Solutions:**
```python
# 1. Check backend health
health = client.read_resource("ims://health")
print(health)  # Look for graph_db status

# 2. Verify node type is valid
# Valid types: Decision, Bug, Feature, Component, Correction, Reflection, Pattern, Lesson

# 3. Ensure required properties exist
node_id = ims.graph.create_node(
    node_type="Decision",
    properties={
        "text": "Required: decision description",
        "project_id": "Required: project identifier",
        "rationale": "Optional: why this decision"
    }
)
```

**Backend-side checks (if you control IMS backend):**
- Verify Neo4j is running: `docker ps | grep neo4j` or check Neo4j service
- Check backend logs for Neo4j connection errors
- Confirm ontology schema initialized: `MATCH (n) RETURN labels(n) LIMIT 10` in Neo4j browser

### Context Search Not Returning Graph Results

**Symptom:** `context_search()` returns only vector results, no graph expansion

**Likely causes:**
1. Graph expansion disabled: `expand_graph=False`
2. No graph nodes exist yet (pre-ontology data)
3. Graph entities not related to vector search results

**Solutions:**
```python
# 1. Explicitly enable graph expansion (default is True)
results = ims.context_rag.context_search(
    project_id="my-app",
    query="your query",
    sources=["memories"],  # Memories most likely to have graph nodes
    expand_graph=True,     # Explicitly enabled
    graph_depth=2          # Increase if needed
)

# 2. Check if graph nodes exist
from app.ims_client import IMSClient
ims = IMSClient()
try:
    # Attempt to query graph
    impact = ims.graph.impact_analysis(
        entity_id="any-decision-id",
        entity_type="Decision"
    )
    print("Graph backend is operational")
except Exception as e:
    print(f"Graph backend issue: {e}")

# 3. Store some decisions/issues to populate graph
ims.memory_core.store_memory(
    project_id="my-app",
    text="Use PostgreSQL for relational data",
    kind="decision",  # Creates Decision node
    tags=["database"]
)
```

### Memory Storage Slower After Ontology Upgrade

**Symptom:** `store_memory()` takes 200-300ms instead of previous 100ms

**Explanation:** This is expected for `kind="decision"`/`"issue"` due to graph node creation. Not a bug.

**Solutions:**

1. **Adjust expectations:** Graph node creation adds 50-100ms overhead for decisions/issues. This is the cost of enabling relationships and impact analysis.

2. **For high-frequency storage of non-decision data:**
   ```python
   # Use kind="fact" or "note" to skip graph node creation
   ims.memory_core.store_memory(
       project_id="my-app",
       text="Log entry: request took 150ms",
       kind="fact",  # No graph node, faster
       tags=["performance"]
   )
   ```

3. **Batch operations:** If storing many decisions, group related ones and create relationships afterward:
   ```python
   # Store decisions
   decision_ids = []
   for decision_text in decisions:
       id = ims.memory_core.store_memory(
           project_id="my-app",
           text=decision_text,
           kind="decision"
       )
       decision_ids.append(id)
   
   # Create relationships in batch (future optimization)
   # Currently, relationships are created one at a time
   ```

### Connection Timeouts

**Symptom:** `httpx.ReadTimeout` or `TimeoutException`

**Likely causes:**
1. IMS backend overloaded or slow
2. Graph query traversing too many relationships
3. Network latency to IMS backend

**Solutions:**

1. **Increase timeout:**
   ```bash
   export IMS_HTTP_TIMEOUT=10.0  # Default is 5.0 seconds
   ```

2. **Reduce graph traversal depth:**
   ```python
   results = ims.context_rag.context_search(
       project_id="my-app",
       query="query",
       sources=["memories"],
       expand_graph=True,
       graph_depth=1  # Reduce from default 2
   )
   ```

3. **Check backend health:**
   ```python
   health = client.read_resource("ims://health")
   # Look for slow response times or error status
   ```

### Invalid Relationship Types

**Symptom:** `create_relationship()` fails with validation error

**Valid relationship types:**
- `implements` (Feature → Decision)
- `blocks` (Bug → Feature)
- `affects` (Decision → Component)
- `depends_on` (Component → Component)
- `supersedes` (Decision → Decision)
- `fixed_by` (Bug → Decision)
- `worked_on` (Session → Feature/Bug)
- `addresses` (Correction → Bug/Issue)
- `inspired_by` (Pattern → Correction, Reflection)
- `learned_from` (Lesson → Bug, Decision, Reflection)
- `documents` (Reflection → Session/Decision)
- `applied_to` (Pattern → Component)
- `tagged_with` (any → Tag)
- `relates_to` (generic relationship)
- `precedes` (temporal ordering)
- `contains` (composition)

**Solution:**
```python
# Use valid relationship type
ims.graph.create_relationship(
    from_id=decision_id,
    rel_type="affects",  # Must be from list above
    to_id=component_id
)
```

### Getting Help

**Check resources first:**
```python
from mcp import ClientSession
import mcp.types as types
import asyncio

async def check_capabilities():
    # Connect to ims-mcp server and read capabilities
    # This shows all available tools and resources
    capabilities = await session.read_resource(
        types.ReadResourceRequest(
            uri="ims://capabilities"
        )
    )
    print(capabilities)

asyncio.run(check_capabilities())
```

**Common issues:**
- **Backend unreachable:** Check `IMS_BASE_URL` env var, ensure backend is running
- **SSL errors:** Set `IMS_VERIFY_SSL=false` for local dev (not production)
- **Authentication issues:** IMS backend currently does not require auth; if you see auth errors, check your `IMS_BASE_URL`
- **Stale cache:** Restart MCP server to clear any client-side caches

**Reporting bugs:**
1. Check IMS backend logs for errors
2. Include MCP tool call that failed (redact sensitive data)
3. Include backend API response if available
4. Note IMS backend version and Neo4j version
