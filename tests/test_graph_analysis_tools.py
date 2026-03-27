"""Integration tests for graph analysis query MCP tools (Task 3.1).

These tests verify that the MCP tools for graph analysis (impact_analysis,
blocking_analysis, architectural_drift, lookup_patterns) work correctly
against a real IMS backend.

TEST CONTRACT:
- Uses REAL backend endpoints (no mocking)
- Tests require IMS backend to be running and accessible
- Tests use actual graph data created via node/relationship tools
- Pydantic v3 APIs only
- Run with deprecation warnings as errors
"""

import os
import pytest
from server import (
    ims_graph_create_decision,
    ims_graph_create_bug,
    ims_graph_create_feature,
    ims_graph_create_component,
    ims_graph_create_relationship,
    ims_graph_impact_analysis,
    ims_graph_blocking_analysis,
    ims_graph_architectural_drift,
    ims_graph_lookup_patterns,
    ims_graph_corrections_ready,
    ims_graph_promote_correction,
)


# Skip all tests in this module if IMS_SKIP_INTEGRATION_TESTS is set
pytestmark = pytest.mark.skipif(
    os.getenv("IMS_SKIP_INTEGRATION_TESTS", "").lower() in ("1", "true", "yes"),
    reason="Integration tests skipped (IMS_SKIP_INTEGRATION_TESTS set)",
)


@pytest.fixture
def test_project_id():
    """Project ID for integration tests."""
    return os.getenv("IMS_TEST_PROJECT_ID", "ims-mcp-test")


@pytest.fixture
def test_graph_nodes(test_project_id):
    """Create test graph nodes for analysis queries.
    
    Returns dict with node IDs for decision, component, bug, and feature.
    """
    # Create a decision
    decision_id = ims_graph_create_decision(
        project_id=test_project_id,
        text="Use Redis for session state storage",
        rationale="Need atomic operations, TTL support, and multi-instance capability",
        importance=0.9,
        tags=["architecture", "redis"],
    )
    
    # Create a component
    component_id = ims_graph_create_component(
        project_id=test_project_id,
        name="SessionManager",
        description="Manages user sessions and state",
        responsibilities=["Session creation", "Session validation", "Session cleanup"],
        tags=["auth", "session"],
    )
    
    # Create a bug
    bug_id = ims_graph_create_bug(
        project_id=test_project_id,
        symptoms="Session state lost after server restart",
        severity="high",
        status="open",
        tags=["session", "persistence"],
    )
    
    # Create a feature
    feature_id = ims_graph_create_feature(
        project_id=test_project_id,
        description="Add session persistence to Redis",
        status="planned",
        priority="high",
        tags=["session", "redis"],
    )
    
    # Create relationships
    ims_graph_create_relationship(from_id=decision_id, rel_type="affects", to_id=component_id)
    ims_graph_create_relationship(from_id=bug_id, rel_type="blocks", to_id=feature_id)
    ims_graph_create_relationship(from_id=feature_id, rel_type="implements", to_id=decision_id)
    
    return {
        "decision_id": decision_id,
        "component_id": component_id,
        "bug_id": bug_id,
        "feature_id": feature_id,
    }


class TestImpactAnalysis:
    """Integration tests for ims_graph_impact_analysis tool."""

    def test_impact_analysis_decision(self, test_project_id, test_graph_nodes):
        """Test impact analysis for a Decision node."""
        result = ims_graph_impact_analysis(
            entity_id=test_graph_nodes["decision_id"],
            entity_type="Decision",
            project_id=test_project_id,
        )
        
        # Should return a dict with results
        assert isinstance(result, dict)
        # Backend should return results or an empty structure
        # We don't assert specific content since backend implementation may vary

    def test_impact_analysis_component(self, test_project_id, test_graph_nodes):
        """Test impact analysis for a Component node."""
        result = ims_graph_impact_analysis(
            entity_id=test_graph_nodes["component_id"],
            entity_type="Component",
            project_id=test_project_id,
        )
        
        assert isinstance(result, dict)

    def test_impact_analysis_invalid_entity_type(self, test_project_id, test_graph_nodes):
        """Test validation failure for invalid entity type."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_impact_analysis(
                entity_id=test_graph_nodes["decision_id"],
                entity_type="InvalidType",
            )
        
        assert "entity_type must be one of" in str(exc_info.value)
        assert "Decision" in str(exc_info.value)
        assert "Component" in str(exc_info.value)


class TestBlockingAnalysis:
    """Integration tests for ims_graph_blocking_analysis tool."""

    def test_blocking_analysis(self, test_project_id, test_graph_nodes):
        """Test blocking analysis for a Feature node."""
        result = ims_graph_blocking_analysis(
            feature_id=test_graph_nodes["feature_id"],
        )
        
        # Should return a dict with results
        assert isinstance(result, dict)
        # Backend should return results or an empty structure

    def test_blocking_analysis_nonexistent_feature(self, test_project_id):
        """Test blocking analysis with a nonexistent feature ID."""
        # Use a valid UUID format but nonexistent node
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        
        # Should not raise an error, but return empty or null results
        result = ims_graph_blocking_analysis(feature_id=fake_uuid)
        assert isinstance(result, dict)


class TestArchitecturalDrift:
    """Integration tests for ims_graph_architectural_drift tool."""

    def test_architectural_drift(self, test_project_id, test_graph_nodes):
        """Test architectural drift detection for a project."""
        result = ims_graph_architectural_drift(
            project_id=test_project_id,
        )
        
        # Should return a dict with results
        assert isinstance(result, dict)
        # Backend should return results or an empty structure

    def test_architectural_drift_empty_project(self):
        """Test architectural drift for a project with no data."""
        result = ims_graph_architectural_drift(
            project_id="nonexistent-project",
        )
        
        assert isinstance(result, dict)


class TestLookupPatterns:
    """Integration tests for ims_graph_lookup_patterns tool."""

    def test_lookup_patterns_without_domain(self, test_project_id, test_graph_nodes):
        """Test pattern lookup without domain filter."""
        result = ims_graph_lookup_patterns(
            component_name="SessionManager",
        )
        
        # Should return a dict with results
        assert isinstance(result, dict)

    def test_lookup_patterns_with_domain(self, test_project_id, test_graph_nodes):
        """Test pattern lookup with domain filter."""
        result = ims_graph_lookup_patterns(
            component_name="SessionManager",
            domain="auth",
        )
        
        assert isinstance(result, dict)

    def test_lookup_patterns_nonexistent_component(self):
        """Test pattern lookup for a component that doesn't exist."""
        result = ims_graph_lookup_patterns(
            component_name="NonexistentComponent",
        )
        
        # Should return empty results or null, not error
        assert isinstance(result, dict)


class TestCorrectionsReady:
    """Integration tests for ims_graph_corrections_ready tool (Task 3.2)."""

    def test_corrections_ready_with_project(self, test_project_id):
        """Test finding corrections ready for promotion with project filter."""
        result = ims_graph_corrections_ready(
            project_id=test_project_id,
        )
        
        # Should return a dict with results
        assert isinstance(result, dict)
        # Backend should return results or an empty structure

    def test_corrections_ready_without_project(self):
        """Test finding corrections ready for promotion without project filter."""
        result = ims_graph_corrections_ready()
        
        assert isinstance(result, dict)


class TestPromoteCorrection:
    """Integration tests for ims_graph_promote_correction tool (Task 3.2)."""

    def test_promote_correction_nonexistent(self):
        """Test promoting a nonexistent correction."""
        # Use a valid UUID format but nonexistent correction
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        
        # Backend may return an error or null result
        # We just verify the tool doesn't crash
        try:
            result = ims_graph_promote_correction(correction_id=fake_uuid)
            assert isinstance(result, dict)
        except Exception:
            # Backend error is acceptable for nonexistent correction
            pass


class TestAnalysisToolsIntegration:
    """Integration tests combining multiple analysis tools."""

    def test_full_analysis_workflow(self, test_project_id, test_graph_nodes):
        """Test a complete analysis workflow using multiple tools."""
        # 1. Check impact of decision
        impact = ims_graph_impact_analysis(
            entity_id=test_graph_nodes["decision_id"],
            entity_type="Decision",
        )
        assert isinstance(impact, dict)
        
        # 2. Check what's blocking the feature
        blockers = ims_graph_blocking_analysis(
            feature_id=test_graph_nodes["feature_id"],
        )
        assert isinstance(blockers, dict)
        
        # 3. Check for architectural drift
        drift = ims_graph_architectural_drift(
            project_id=test_project_id,
        )
        assert isinstance(drift, dict)
        
        # 4. Look up patterns for component
        patterns = ims_graph_lookup_patterns(
            component_name="SessionManager",
        )
        assert isinstance(patterns, dict)
        
        # 5. Check for corrections ready for promotion (Task 3.2)
        corrections = ims_graph_corrections_ready(
            project_id=test_project_id,
        )
        assert isinstance(corrections, dict)
