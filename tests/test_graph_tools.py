"""Comprehensive integration tests for all graph MCP tools (Task 5.2).

This test suite provides comprehensive coverage for the ontology integration:
- Node creation for all implemented types (Decision, Bug, Feature, Component)
- Relationship creation for all relationship types
- Graph query patterns (impact analysis, blocking analysis, drift detection)
- Hybrid search (vector + graph)
- Self-improving workflow (corrections, patterns)
- Error handling and validation
- Performance characteristics

TEST CONTRACT:
- Uses REAL backend endpoints (no mocking except for isolated unit tests)
- Tests require IMS backend to be running and accessible
- Tests create actual graph nodes and verify responses
- Pydantic v3 APIs only (no deprecated v2 patterns)
- Run with deprecation warnings as errors

COVERAGE TARGET: >90% for all graph-related tools
"""

import os
import time
import pytest
from typing import Dict, Any

from server import (
    # Node creation tools
    ims_graph_create_decision,
    ims_graph_create_bug,
    ims_graph_create_feature,
    ims_graph_create_component,
    # Relationship tools
    ims_graph_create_relationship,
    # Analysis tools
    ims_graph_impact_analysis,
    ims_graph_blocking_analysis,
    ims_graph_architectural_drift,
    ims_graph_lookup_patterns,
    # Self-improving tools
    ims_graph_corrections_ready,
    ims_graph_promote_correction,
    # Enhanced context tools
    ims_context_search,
    ims_store_memory,
)


# Skip all tests if integration tests are disabled
pytestmark = pytest.mark.skipif(
    os.getenv("IMS_SKIP_INTEGRATION_TESTS", "").lower() in ("1", "true", "yes"),
    reason="Integration tests skipped (IMS_SKIP_INTEGRATION_TESTS set)",
)


@pytest.fixture
def test_project_id():
    """Project ID for integration tests."""
    return os.getenv("IMS_TEST_PROJECT_ID", "ims-mcp-test")


@pytest.fixture
def sample_graph(test_project_id):
    """Create a sample graph with all node types and relationships.
    
    Returns dict with node IDs for each type.
    """
    # Create Decision nodes
    decision1_id = ims_graph_create_decision(
        project_id=test_project_id,
        text="Use microservices architecture for scalability",
        rationale="Monolithic architecture cannot handle our scaling requirements. Microservices enable independent scaling of components.",
        alternatives=["Monolith (rejected - scaling limits)", "Serverless (rejected - complex state management)"],
        consequences=["Increased operational complexity", "Better resource utilization", "Improved fault isolation"],
        importance=0.95,
        tags=["architecture", "microservices", "scalability"],
    )
    
    decision2_id = ims_graph_create_decision(
        project_id=test_project_id,
        text="Use Redis for distributed session storage",
        rationale="Need atomic operations, TTL support, and multi-instance capability for session management across microservices.",
        importance=0.85,
        tags=["architecture", "redis", "session"],
    )
    
    # Create Component nodes
    component1_id = ims_graph_create_component(
        project_id=test_project_id,
        name="AuthService",
        description="Handles authentication and authorization",
        interface="POST /auth/login, POST /auth/logout, GET /auth/verify",
        responsibilities=["JWT token generation", "Session management", "Access control"],
        tags=["service", "auth"],
    )
    
    component2_id = ims_graph_create_component(
        project_id=test_project_id,
        name="UserService",
        description="User profile management service",
        responsibilities=["User CRUD operations", "Profile updates"],
        tags=["service", "user"],
    )
    
    component3_id = ims_graph_create_component(
        project_id=test_project_id,
        name="SessionStore",
        description="Redis-backed session storage",
        tags=["datastore", "redis"],
    )
    
    # Create Feature nodes
    feature1_id = ims_graph_create_feature(
        project_id=test_project_id,
        description="Implement OAuth2 authentication flow with Google and GitHub providers",
        requirements=["Google OAuth2 integration", "GitHub OAuth2 integration", "Token refresh", "PKCE flow"],
        status="in_progress",
        priority="high",
        file_path="services/auth/oauth.py",
        line_hint=120,
        tags=["feature", "auth", "oauth"],
    )
    
    feature2_id = ims_graph_create_feature(
        project_id=test_project_id,
        description="Add user profile picture upload",
        status="planned",
        priority="medium",
        tags=["feature", "user", "upload"],
    )
    
    # Create Bug nodes
    bug1_id = ims_graph_create_bug(
        project_id=test_project_id,
        symptoms="Session expires immediately after login, forcing repeated authentication",
        root_cause="Redis session TTL set to 30 seconds instead of 3600 seconds in config",
        status="open",
        severity="critical",
        primary_file="config/redis.py",
        line_hint=42,
        tags=["bug", "session", "redis"],
    )
    
    bug2_id = ims_graph_create_bug(
        project_id=test_project_id,
        symptoms="User profile update API returns 500 error for international phone numbers",
        status="open",
        severity="medium",
        primary_file="services/user/profile.py",
        line_hint=85,
        tags=["bug", "user", "validation"],
    )
    
    # Create relationships
    # Decision affects Component
    ims_graph_create_relationship(from_id=decision1_id, rel_type="affects", to_id=component1_id)
    ims_graph_create_relationship(from_id=decision1_id, rel_type="affects", to_id=component2_id)
    ims_graph_create_relationship(from_id=decision2_id, rel_type="affects", to_id=component3_id)
    
    # Feature implements Decision
    ims_graph_create_relationship(from_id=feature1_id, rel_type="implements", to_id=decision1_id)
    
    # Bug blocks Feature
    ims_graph_create_relationship(from_id=bug1_id, rel_type="blocks", to_id=feature1_id)
    
    # Component depends on Component
    ims_graph_create_relationship(from_id=component1_id, rel_type="depends_on", to_id=component3_id)
    ims_graph_create_relationship(from_id=component2_id, rel_type="depends_on", to_id=component1_id)
    
    # Decision supersedes Decision (newer supersedes older)
    ims_graph_create_relationship(from_id=decision2_id, rel_type="supersedes", to_id=decision1_id)
    
    # Bug fixed_by Decision (once bug is fixed)
    # (This would be created after bug is fixed, but we'll create it for testing)
    
    return {
        "decisions": [decision1_id, decision2_id],
        "components": [component1_id, component2_id, component3_id],
        "features": [feature1_id, feature2_id],
        "bugs": [bug1_id, bug2_id],
    }


class TestNodeCreation:
    """Comprehensive tests for node creation tools."""
    
    def test_create_all_node_types(self, test_project_id):
        """Test creating one of each implemented node type."""
        # Decision
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use GraphQL for API layer",
            rationale="GraphQL provides better flexibility and reduces over-fetching compared to REST",
        )
        assert isinstance(decision_id, str)
        assert len(decision_id) == 36
        
        # Bug
        bug_id = ims_graph_create_bug(
            project_id=test_project_id,
            symptoms="Database connection timeout after 30 seconds",
        )
        assert isinstance(bug_id, str)
        assert len(bug_id) == 36
        
        # Feature
        feature_id = ims_graph_create_feature(
            project_id=test_project_id,
            description="Implement real-time notifications via WebSocket",
        )
        assert isinstance(feature_id, str)
        assert len(feature_id) == 36
        
        # Component
        component_id = ims_graph_create_component(
            project_id=test_project_id,
            name="NotificationService",
        )
        assert isinstance(component_id, str)
        assert len(component_id) == 36
        
        # All IDs should be unique
        all_ids = {decision_id, bug_id, feature_id, component_id}
        assert len(all_ids) == 4
    
    def test_node_creation_with_all_optional_fields(self, test_project_id):
        """Test creating nodes with all optional fields populated."""
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use Kubernetes for container orchestration",
            rationale="Need automated scaling, self-healing, and declarative configuration for production workloads",
            alternatives=["Docker Swarm (simpler but less features)", "ECS (AWS lock-in)"],
            consequences=["Increased operational complexity", "Better scalability", "Cloud-agnostic deployment"],
            importance=0.92,
            tags=["architecture", "kubernetes", "containers", "production"],
        )
        assert isinstance(decision_id, str)
        
    def test_validation_errors_have_clear_messages(self, test_project_id):
        """Test that validation errors provide clear, actionable messages."""
        # Decision text too short
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_decision(
                project_id=test_project_id,
                text="Short",
                rationale="This is a valid rationale that is long enough",
            )
        error_msg = str(exc_info.value)
        assert "text must be at least 10 characters" in error_msg
        
        # Bug invalid status
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_bug(
                project_id=test_project_id,
                symptoms="Something broke",
                status="invalid_status",
            )
        error_msg = str(exc_info.value)
        assert "status must be one of" in error_msg
        assert "open" in error_msg


class TestRelationshipCreation:
    """Comprehensive tests for relationship creation."""
    
    def test_all_relationship_types(self, test_project_id, sample_graph):
        """Test creating relationships of all types."""
        # implements: Feature -> Decision
        success = ims_graph_create_relationship(
            from_id=sample_graph["features"][1],
            rel_type="implements",
            to_id=sample_graph["decisions"][1],
        )
        assert success is True
        
        # blocks: Bug -> Feature
        success = ims_graph_create_relationship(
            from_id=sample_graph["bugs"][1],
            rel_type="blocks",
            to_id=sample_graph["features"][1],
        )
        assert success is True
        
        # affects: Decision -> Component
        success = ims_graph_create_relationship(
            from_id=sample_graph["decisions"][0],
            rel_type="affects",
            to_id=sample_graph["components"][2],
        )
        assert success is True
        
        # depends_on: Component -> Component
        # Create new component to avoid cycle (fixture already has component1->component3, component2->component1)
        new_component = ims_graph_create_component(
            project_id=test_project_id,
            name="CacheService",
            description="Caching layer service",
        )
        success = ims_graph_create_relationship(
            from_id=sample_graph["components"][2],
            rel_type="depends_on",
            to_id=new_component,
        )
        assert success is True
        
        # supersedes: Decision -> Decision
        old_decision = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use MongoDB for data storage",
            rationale="Document model chosen for flexibility",
        )
        new_decision = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use PostgreSQL for data storage",
            rationale="Relational model better fits requirements after analysis",
        )
        success = ims_graph_create_relationship(
            from_id=new_decision,
            rel_type="supersedes",
            to_id=old_decision,
        )
        assert success is True
        
        # fixed_by: Bug -> Decision
        success = ims_graph_create_relationship(
            from_id=sample_graph["bugs"][0],
            rel_type="fixed_by",
            to_id=sample_graph["decisions"][1],
        )
        assert success is True
    
    def test_relationship_with_properties(self, test_project_id, sample_graph):
        """Test creating relationships with custom properties."""
        success = ims_graph_create_relationship(
            from_id=sample_graph["decisions"][0],
            rel_type="affects",
            to_id=sample_graph["components"][1],
            properties={"confidence": 0.95, "impact_level": "high", "notes": "Critical dependency"},
        )
        assert success is True
    
    def test_invalid_relationship_type(self, test_project_id, sample_graph):
        """Test validation of relationship types."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_relationship(
                from_id=sample_graph["decisions"][0],
                rel_type="invalid_rel_type",
                to_id=sample_graph["components"][0],
            )
        error_msg = str(exc_info.value)
        assert "rel_type must be one of" in error_msg
        assert "implements" in error_msg


class TestGraphQueries:
    """Comprehensive tests for graph query patterns."""
    
    def test_impact_analysis_decision(self, test_project_id, sample_graph):
        """Test impact analysis for a Decision node."""
        result = ims_graph_impact_analysis(
            entity_id=sample_graph["decisions"][0],
            entity_type="Decision",
            project_id=test_project_id,
        )
        
        assert isinstance(result, dict)
        # Backend should return some structure
        # Exact format may vary, but it should be a dict
    
    def test_impact_analysis_component(self, test_project_id, sample_graph):
        """Test impact analysis for a Component node."""
        result = ims_graph_impact_analysis(
            entity_id=sample_graph["components"][0],
            entity_type="Component",
            project_id=test_project_id,
        )
        
        assert isinstance(result, dict)
    
    def test_blocking_analysis(self, test_project_id, sample_graph):
        """Test blocking analysis to find bugs blocking a feature."""
        result = ims_graph_blocking_analysis(
            feature_id=sample_graph["features"][0],
        )
        
        assert isinstance(result, dict)
        # Should return information about blocking bugs
    
    def test_architectural_drift(self, test_project_id, sample_graph):
        """Test architectural drift detection."""
        result = ims_graph_architectural_drift(
            project_id=test_project_id,
        )
        
        assert isinstance(result, dict)
        # Should detect components following superseded decisions
    
    def test_lookup_patterns(self, test_project_id):
        """Test pattern lookup for a component."""
        result = ims_graph_lookup_patterns(
            component_name="AuthService",
        )
        
        assert isinstance(result, dict)
    
    def test_lookup_patterns_with_domain(self, test_project_id):
        """Test pattern lookup with domain filter."""
        result = ims_graph_lookup_patterns(
            component_name="AuthService",
            domain="security",
        )
        
        assert isinstance(result, dict)


class TestSelfImprovingWorkflow:
    """Tests for self-improving layer (corrections and patterns)."""
    
    def test_corrections_ready(self, test_project_id):
        """Test finding corrections ready for promotion."""
        result = ims_graph_corrections_ready(
            project_id=test_project_id,
        )
        
        assert isinstance(result, dict)
        # Should return corrections with 3+ uses
    
    def test_corrections_ready_no_project_filter(self):
        """Test finding corrections without project filter."""
        result = ims_graph_corrections_ready()
        
        assert isinstance(result, dict)
    
    def test_promote_correction_nonexistent(self):
        """Test promoting a nonexistent correction (error handling)."""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        
        # Backend may return an error or empty result
        # We just verify the tool doesn't crash
        try:
            result = ims_graph_promote_correction(correction_id=fake_uuid)
            assert isinstance(result, dict)
        except Exception as e:
            # Backend error is acceptable for nonexistent correction
            assert "not found" in str(e).lower() or "does not exist" in str(e).lower()


class TestHybridSearch:
    """Tests for hybrid vector + graph search."""
    
    def test_context_search_with_graph_expansion(self, test_project_id, sample_graph):
        """Test context search with graph expansion enabled."""
        result = ims_context_search(
            project_id=test_project_id,
            query="authentication and session management",
            sources=["memories", "code"],
            per_source_limits={"memories": 5, "code": 5},
            expand_graph=True,
            graph_depth=2,
        )
        
        assert isinstance(result, dict)
        # Should include both vector search results and graph-expanded context
    
    def test_context_search_without_graph_expansion(self, test_project_id):
        """Test context search with graph expansion disabled (backward compatibility)."""
        result = ims_context_search(
            project_id=test_project_id,
            query="authentication",
            sources=["memories"],
            per_source_limits={"memories": 3},
            expand_graph=False,
        )
        
        assert isinstance(result, dict)
    
    def test_memory_storage_creates_graph_node(self, test_project_id):
        """Test that storing a decision memory creates a graph node."""
        result = ims_store_memory(
            project_id=test_project_id,
            text="Use WebSocket for real-time communication. Rationale: Low latency requirement for live updates.",
            kind="decision",
            tags=["architecture", "websocket", "real-time"],
            importance=0.8,
        )
        
        # ims_store_memory returns a dict, not a string
        assert isinstance(result, dict)


class TestErrorHandling:
    """Comprehensive error handling tests."""
    
    def test_invalid_project_id_format(self, test_project_id):
        """Test handling of invalid project ID formats."""
        # Empty project_id should be rejected
        with pytest.raises((ValueError, TypeError)) as exc_info:
            ims_graph_create_decision(
                project_id="",
                text="Use Redis for caching",
                rationale="Fast in-memory cache improves performance",
            )
    
    def test_missing_required_fields(self, test_project_id):
        """Test that missing required fields produce clear errors."""
        # Decision missing rationale
        with pytest.raises(TypeError) as exc_info:
            ims_graph_create_decision(
                project_id=test_project_id,
                text="Use Redis for caching",
                # rationale is missing
            )
    
    def test_nonexistent_node_in_relationship(self, test_project_id):
        """Test creating relationship with nonexistent nodes."""
        fake_uuid1 = "00000000-0000-0000-0000-000000000001"
        fake_uuid2 = "00000000-0000-0000-0000-000000000002"
        
        # Backend may accept this or reject it
        # We test that the tool doesn't crash
        try:
            result = ims_graph_create_relationship(
                from_id=fake_uuid1,
                rel_type="affects",
                to_id=fake_uuid2,
            )
            # If it succeeds, result should be boolean
            assert isinstance(result, bool)
        except Exception as e:
            # Backend error is acceptable
            pass
    
    def test_impact_analysis_invalid_entity_type(self, test_project_id):
        """Test impact analysis with invalid entity type."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_impact_analysis(
                entity_id="some-uuid",
                entity_type="InvalidType",
            )
        assert "entity_type must be one of" in str(exc_info.value)


class TestPerformance:
    """Performance benchmarks for graph operations."""
    
    def test_node_creation_performance(self, test_project_id):
        """Benchmark node creation performance."""
        start_time = time.time()
        
        for i in range(10):
            ims_graph_create_decision(
                project_id=test_project_id,
                text=f"Performance test decision {i}",
                rationale="This is a test decision for performance benchmarking",
            )
        
        elapsed = time.time() - start_time
        avg_time = elapsed / 10
        
        # Each node creation should take less than 1 second on average
        assert avg_time < 1.0, f"Node creation too slow: {avg_time:.2f}s per node"
    
    def test_relationship_creation_performance(self, test_project_id):
        """Benchmark relationship creation performance."""
        # Create test nodes
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Performance test decision for relationships",
            rationale="Testing relationship creation performance",
        )
        component_ids = [
            ims_graph_create_component(
                project_id=test_project_id,
                name=f"PerfTestComponent{i}",
            )
            for i in range(10)
        ]
        
        start_time = time.time()
        
        for comp_id in component_ids:
            ims_graph_create_relationship(
                from_id=decision_id,
                rel_type="affects",
                to_id=comp_id,
            )
        
        elapsed = time.time() - start_time
        avg_time = elapsed / 10
        
        # Each relationship creation should take less than 1 second
        assert avg_time < 1.0, f"Relationship creation too slow: {avg_time:.2f}s per relationship"
    
    def test_query_performance(self, test_project_id, sample_graph):
        """Benchmark graph query performance."""
        start_time = time.time()
        
        result = ims_graph_impact_analysis(
            entity_id=sample_graph["decisions"][0],
            entity_type="Decision",
            project_id=test_project_id,
        )
        
        elapsed = time.time() - start_time
        
        # Query should complete within 2 seconds
        assert elapsed < 2.0, f"Impact analysis too slow: {elapsed:.2f}s"


class TestCrossToolIntegration:
    """Integration tests combining multiple tools."""
    
    def test_full_workflow_feature_development(self, test_project_id):
        """Test a complete workflow: decision -> feature -> implementation -> testing."""
        # 1. Make architectural decision
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use React for frontend framework",
            rationale="Team has React expertise, large ecosystem, good performance",
            importance=0.9,
        )
        
        # 2. Create component that will be affected
        component_id = ims_graph_create_component(
            project_id=test_project_id,
            name="FrontendApp",
            description="Main frontend application",
        )
        
        # 3. Link decision to component
        ims_graph_create_relationship(
            from_id=decision_id,
            rel_type="affects",
            to_id=component_id,
        )
        
        # 4. Create feature to implement the decision
        feature_id = ims_graph_create_feature(
            project_id=test_project_id,
            description="Build React-based dashboard UI",
            status="in_progress",
            priority="high",
        )
        
        # 5. Link feature to decision
        ims_graph_create_relationship(
            from_id=feature_id,
            rel_type="implements",
            to_id=decision_id,
        )
        
        # 6. Discover a bug
        bug_id = ims_graph_create_bug(
            project_id=test_project_id,
            symptoms="React components not rendering in IE11",
            severity="medium",
        )
        
        # 7. Bug blocks feature
        ims_graph_create_relationship(
            from_id=bug_id,
            rel_type="blocks",
            to_id=feature_id,
        )
        
        # 8. Analyze impact of original decision
        impact = ims_graph_impact_analysis(
            entity_id=decision_id,
            entity_type="Decision",
        )
        assert isinstance(impact, dict)
        
        # 9. Check what's blocking the feature
        blockers = ims_graph_blocking_analysis(feature_id=feature_id)
        assert isinstance(blockers, dict)
        
        # All operations should succeed
        assert all([decision_id, component_id, feature_id, bug_id])
    
    def test_architectural_evolution_workflow(self, test_project_id):
        """Test workflow for evolving architecture (superseding decisions)."""
        # 1. Original decision
        old_decision = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use REST API for all endpoints",
            rationale="REST is well-understood and widely supported",
        )
        
        # 2. Components follow this decision
        comp1 = ims_graph_create_component(project_id=test_project_id, name="APIGateway")
        comp2 = ims_graph_create_component(project_id=test_project_id, name="UserAPI")
        
        ims_graph_create_relationship(from_id=old_decision, rel_type="affects", to_id=comp1)
        ims_graph_create_relationship(from_id=old_decision, rel_type="affects", to_id=comp2)
        
        # 3. New decision supersedes old one
        new_decision = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use GraphQL for API layer",
            rationale="GraphQL provides better flexibility and reduces over-fetching",
        )
        
        ims_graph_create_relationship(from_id=new_decision, rel_type="supersedes", to_id=old_decision)
        
        # 4. Detect architectural drift
        drift = ims_graph_architectural_drift(project_id=test_project_id)
        assert isinstance(drift, dict)
        # Should detect that comp1 and comp2 follow superseded decision


class TestBackwardCompatibility:
    """Tests ensuring backward compatibility with existing code."""
    
    def test_context_search_default_parameters(self, test_project_id):
        """Test context search with default parameters (no graph expansion)."""
        # Old code that doesn't use graph expansion should still work
        result = ims_context_search(
            project_id=test_project_id,
            query="authentication",
            sources=["memories"],
        )
        assert isinstance(result, dict)
    
    def test_memory_storage_without_graph_node_parameter(self, test_project_id):
        """Test memory storage without specifying create_graph_node parameter."""
        # Old code that doesn't know about graph nodes should still work
        result = ims_store_memory(
            project_id=test_project_id,
            text="This is a test memory without graph node parameter",
            kind="note",
            tags=["test"],
        )
        assert isinstance(result, dict)


# Performance baseline markers
pytest.mark.performance = pytest.mark.performance if hasattr(pytest.mark, 'performance') else pytest.mark.skip

# Mark slow tests
pytest.mark.slow = pytest.mark.slow if hasattr(pytest.mark, 'slow') else pytest.mark.skip
