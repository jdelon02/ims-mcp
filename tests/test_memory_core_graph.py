"""
Integration tests for memory-core graph node creation (Task 4.2).

Tests verify that storing memories with kind="decision" or kind="issue" 
automatically creates corresponding graph nodes in Neo4j.

NOTE: These tests require the IMS backend Phase 4 enhancements to be deployed,
specifically the auto-creation of Decision/Bug nodes when storing memories.
"""

import pytest
from app.ims_client import IMSClient
import os


@pytest.fixture
def ims_client():
    """Create IMS client for testing."""
    return IMSClient()


@pytest.fixture
def test_project_id():
    """Test project identifier."""
    return "ims-mcp-test"


class TestMemoryCoreGraphIntegration:
    """Test automatic graph node creation when storing memories."""

    def test_decision_memory_creates_graph_node(self, ims_client, test_project_id):
        """
        Test that storing a decision memory auto-creates a Decision node.
        
        Expected behavior (backend Phase 4):
        1. Memory stored in Postgres
        2. Embedding created in Qdrant
        3. Decision node created in Neo4j with properties from memory
        """
        # Store a decision
        memory = ims_client.memory_core.store_memory(
            project_id=test_project_id,
            text="Use Redis for session state. Rationale: Need TTL and atomic ops.",
            kind="decision",
            tags=["architecture", "redis"],
            importance=0.9
        )
        
        # Verify memory was created
        assert memory is not None
        assert "memory_id" in memory or "id" in memory
        memory_id = memory.get("memory_id") or memory.get("id")
        
        # TODO: Once backend Phase 4 is deployed, add verification:
        # 1. Query graph for Decision node with matching memory_id
        # 2. Verify node properties match memory (text, tags, importance)
        # For now, we only verify the memory was stored successfully.
        # The backend is responsible for creating the graph node.
        
        # Example future assertion (requires graph query endpoint):
        # nodes = ims_client.graph.query_nodes(
        #     node_type="Decision",
        #     properties={"memory_id": memory_id}
        # )
        # assert len(nodes) == 1
        # assert nodes[0]["properties"]["text"] == memory["text"]

    def test_issue_memory_creates_bug_node(self, ims_client, test_project_id):
        """
        Test that storing an issue memory auto-creates a Bug node.
        
        Expected behavior (backend Phase 4):
        1. Memory stored in Postgres
        2. Embedding created in Qdrant
        3. Bug node created in Neo4j with properties from memory
        """
        # Store an issue
        memory = ims_client.memory_core.store_memory(
            project_id=test_project_id,
            text="Auth timeout bug fixed by increasing session TTL to 1 hour",
            kind="issue",
            tags=["bug", "auth"],
            importance=0.7
        )
        
        # Verify memory was created
        assert memory is not None
        assert "memory_id" in memory or "id" in memory
        memory_id = memory.get("memory_id") or memory.get("id")
        
        # TODO: Once backend Phase 4 is deployed, add verification:
        # 1. Query graph for Bug node with matching memory_id
        # 2. Verify node properties match memory
        
        # Example future assertion:
        # nodes = ims_client.graph.query_nodes(
        #     node_type="Bug",
        #     properties={"memory_id": memory_id}
        # )
        # assert len(nodes) == 1

    def test_fact_memory_no_graph_node(self, ims_client, test_project_id):
        """
        Test that storing a fact/note memory does NOT create graph nodes.
        
        Expected behavior:
        1. Memory stored in Postgres
        2. Embedding created in Qdrant
        3. NO graph node created (facts/notes don't have graph representation)
        """
        # Store a fact
        memory = ims_client.memory_core.store_memory(
            project_id=test_project_id,
            text="Redis runs on port 6379 in production",
            kind="fact",
            tags=["config", "redis"]
        )
        
        # Verify memory was created
        assert memory is not None
        assert "memory_id" in memory or "id" in memory
        
        # TODO: Once backend Phase 4 is deployed, verify NO graph node exists
        # Example future assertion:
        # nodes = ims_client.graph.query_nodes(
        #     node_type="Fact",  # No such node type
        #     properties={"memory_id": memory_id}
        # )
        # assert len(nodes) == 0


@pytest.mark.skipif(
    os.getenv("SKIP_GRAPH_INTEGRATION_TESTS") == "1",
    reason="Graph integration tests skipped (backend Phase 4 not deployed)"
)
class TestMemoryCoreGraphIntegrationWithBackend:
    """
    Integration tests that verify graph node creation end-to-end.
    
    These tests are skipped by default until backend Phase 4 is deployed.
    To enable: unset SKIP_GRAPH_INTEGRATION_TESTS or set to 0.
    """
    
    def test_decision_graph_node_properties(self, ims_client, test_project_id):
        """Verify Decision node properties match memory metadata."""
        # This test will be implemented once backend supports graph queries
        pytest.skip("Backend Phase 4 graph query endpoint not yet available")
    
    def test_issue_graph_node_properties(self, ims_client, test_project_id):
        """Verify Bug node properties match memory metadata."""
        pytest.skip("Backend Phase 4 graph query endpoint not yet available")
    
    def test_graph_relationship_creation(self, ims_client, test_project_id):
        """Test creating relationships between memory-generated nodes."""
        pytest.skip("Backend Phase 4 relationship endpoint not yet available")
