"""Integration tests for context_rag with graph expansion."""

import pytest
from app.ims_client import IMSClient, ContextRagClient


@pytest.fixture
def ims_client():
    """Create an IMSClient instance."""
    return IMSClient()


@pytest.fixture
def context_rag_client(ims_client):
    """Extract the context_rag client."""
    return ims_client.context_rag


def test_context_search_with_graph_expansion_enabled(context_rag_client):
    """Test context_search with graph expansion enabled (default)."""
    result = context_rag_client.context_search(
        project_id="ims-mcp",
        query="session state management",
        sources=["memories"],
        per_source_limits={"memories": 3},
        expand_graph=True,
        graph_depth=2,
    )
    
    # Should return a dict with results
    assert isinstance(result, dict)
    assert "results" in result
    # Results should be a list (may be empty if no data exists)
    assert isinstance(result["results"], list)


def test_context_search_with_graph_expansion_disabled(context_rag_client):
    """Test context_search with graph expansion disabled."""
    result = context_rag_client.context_search(
        project_id="ims-mcp",
        query="authentication",
        sources=["code"],
        per_source_limits={"code": 5},
        expand_graph=False,
        graph_depth=1,
    )
    
    # Should return a dict with results
    assert isinstance(result, dict)
    assert "results" in result
    assert isinstance(result["results"], list)


def test_context_search_default_graph_parameters(context_rag_client):
    """Test that graph expansion defaults are applied correctly."""
    result = context_rag_client.context_search(
        project_id="ims-mcp",
        query="memory storage",
        sources=["memories", "code"],
    )
    
    # Should use default expand_graph=True and graph_depth=2
    assert isinstance(result, dict)
    assert "results" in result


def test_context_search_various_graph_depths(context_rag_client):
    """Test context_search with different graph depth values."""
    for depth in [1, 2, 3]:
        result = context_rag_client.context_search(
            project_id="ims-mcp",
            query="test query",
            sources=["memories"],
            expand_graph=True,
            graph_depth=depth,
        )
        
        assert isinstance(result, dict)
        assert "results" in result
        assert isinstance(result["results"], list)


def test_context_search_backward_compatibility(context_rag_client):
    """Test that old calls without graph params still work."""
    # This simulates a call from old client code that doesn't know about graph params
    result = context_rag_client.context_search(
        project_id="ims-mcp",
        query="test",
        sources=["memories"],
        per_source_limits={"memories": 2},
    )
    
    # Should still work with defaults
    assert isinstance(result, dict)
    assert "results" in result
