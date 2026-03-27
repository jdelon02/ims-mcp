"""Integration tests for graph node creation MCP tools (Task 2.1).

These tests verify that the MCP tools for creating Decision, Bug, Feature, and
Component nodes work correctly against a real IMS backend.

TEST CONTRACT:
- Uses REAL backend endpoints (no mocking)
- Tests require IMS backend to be running and accessible
- Tests create actual graph nodes and verify responses
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


class TestDecisionNodeCreation:
    """Integration tests for ims_graph_create_decision tool."""

    def test_create_decision_minimal(self, test_project_id):
        """Test creating a Decision node with minimal required fields."""
        node_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use PostgreSQL for primary data storage",
            rationale="Relational model fits our domain, ACID guarantees required",
        )
        
        # Should return a valid UUID string
        assert isinstance(node_id, str)
        assert len(node_id) == 36  # UUID format: 8-4-4-4-12
        assert "-" in node_id

    def test_create_decision_full(self, test_project_id):
        """Test creating a Decision node with all fields populated."""
        node_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use Redis for session state storage",
            rationale="Need atomic operations, TTL support, and multi-instance capability for session management",
            alternatives=[
                "File-based sessions (rejected - no concurrency support)",
                "In-memory sessions (rejected - lost on restart)",
            ],
            consequences=[
                "Requires Redis deployment and monitoring",
                "Enables horizontal scaling of application servers",
                "Adds external dependency",
            ],
            importance=0.9,
            tags=["architecture", "redis", "session-state", "high-priority"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_decision_text_too_short(self, test_project_id):
        """Test validation failure when text is too short."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_decision(
                project_id=test_project_id,
                text="Short",  # Less than 10 chars
                rationale="This is a valid rationale that is long enough",
            )
        
        assert "text must be at least 10 characters" in str(exc_info.value)

    def test_create_decision_rationale_too_short(self, test_project_id):
        """Test validation failure when rationale is too short."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_decision(
                project_id=test_project_id,
                text="Use MongoDB for logging",
                rationale="It's good",  # Less than 20 chars
            )
        
        assert "rationale must be at least 20 characters" in str(exc_info.value)

    def test_create_decision_importance_out_of_range(self, test_project_id):
        """Test validation failure when importance is out of range."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_decision(
                project_id=test_project_id,
                text="Use GraphQL for API",
                rationale="Flexible queries and type safety improve developer experience",
                importance=1.5,  # Out of range
            )
        
        assert "importance must be between 0.0 and 1.0" in str(exc_info.value)


class TestBugNodeCreation:
    """Integration tests for ims_graph_create_bug tool."""

    def test_create_bug_minimal(self, test_project_id):
        """Test creating a Bug node with minimal required fields."""
        node_id = ims_graph_create_bug(
            project_id=test_project_id,
            symptoms="Application crashes when processing large JSON payloads over 10MB",
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_bug_full(self, test_project_id):
        """Test creating a Bug node with all fields populated."""
        node_id = ims_graph_create_bug(
            project_id=test_project_id,
            symptoms="Server returns 500 error when JWT token is expired or malformed",
            status="open",
            severity="high",
            root_cause="Missing null check and exception handling in token validation middleware",
            fix="Added try-catch block and null validation before token.verify() call",
            primary_file="auth/middleware.py",
            line_hint=42,
            external_id="gh-jdelon02/ims-mcp-123",
            external_system="github",
            tags=["auth", "jwt", "crash", "security"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_bug_symptoms_too_short(self, test_project_id):
        """Test validation failure when symptoms is too short."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_bug(
                project_id=test_project_id,
                symptoms="Error",  # Less than 10 chars
            )
        
        assert "symptoms must be at least 10 characters" in str(exc_info.value)

    def test_create_bug_invalid_status(self, test_project_id):
        """Test validation failure for invalid status value."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_bug(
                project_id=test_project_id,
                symptoms="Database connection timeout after 30 seconds of inactivity",
                status="invalid_status",
            )
        
        assert "status must be one of" in str(exc_info.value)
        assert "open" in str(exc_info.value)

    def test_create_bug_invalid_severity(self, test_project_id):
        """Test validation failure for invalid severity value."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_bug(
                project_id=test_project_id,
                symptoms="Minor UI alignment issue in mobile view on specific devices",
                severity="ultra_critical",
            )
        
        assert "severity must be one of" in str(exc_info.value)
        assert "critical" in str(exc_info.value)


class TestFeatureNodeCreation:
    """Integration tests for ims_graph_create_feature tool."""

    def test_create_feature_minimal(self, test_project_id):
        """Test creating a Feature node with minimal required fields."""
        node_id = ims_graph_create_feature(
            project_id=test_project_id,
            description="Add OAuth 2.0 authentication support for third-party logins",
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_feature_full(self, test_project_id):
        """Test creating a Feature node with all fields populated."""
        node_id = ims_graph_create_feature(
            project_id=test_project_id,
            description="Implement GraphQL API endpoint for querying project data",
            status="in_progress",
            priority="high",
            requirements=[
                "Support filtering by project_id and user_id",
                "Support pagination with cursor-based navigation",
                "Include authentication via JWT",
            ],
            file_path="api/graphql/schema.py",
            line_hint=150,
            external_id="gh-jdelon02/ims-mcp-456",
            external_system="github",
            tags=["graphql", "api", "query"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_feature_description_too_short(self, test_project_id):
        """Test validation failure when description is too short."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_feature(
                project_id=test_project_id,
                description="Add API",  # Less than 10 chars
            )
        
        assert "description must be at least 10 characters" in str(exc_info.value)

    def test_create_feature_invalid_status(self, test_project_id):
        """Test validation failure for invalid status value."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_feature(
                project_id=test_project_id,
                description="Implement real-time websocket notifications",
                status="pending_approval",
            )
        
        assert "status must be one of" in str(exc_info.value)
        assert "planned" in str(exc_info.value)

    def test_create_feature_invalid_priority(self, test_project_id):
        """Test validation failure for invalid priority value."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_feature(
                project_id=test_project_id,
                description="Add dark mode theme support",
                priority="nice_to_have",
            )
        
        assert "priority must be one of" in str(exc_info.value)
        assert "medium" in str(exc_info.value)


class TestComponentNodeCreation:
    """Integration tests for ims_graph_create_component tool."""

    def test_create_component_minimal(self, test_project_id):
        """Test creating a Component node with minimal required fields."""
        node_id = ims_graph_create_component(
            project_id=test_project_id,
            name="AuthService",
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_component_full(self, test_project_id):
        """Test creating a Component node with all fields populated."""
        node_id = ims_graph_create_component(
            project_id=test_project_id,
            name="SessionManager",
            description="Handles user session lifecycle and validation",
            interface="POST /sessions/create, DELETE /sessions/{id}, GET /sessions/{id}",
            responsibilities=[
                "Session creation and validation",
                "Token generation and verification",
                "Session expiration management",
            ],
            tags=["service", "auth", "sessions"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_component_valid_name_formats(self, test_project_id):
        """Test various valid component name formats."""
        # Alphanumeric
        node_id1 = ims_graph_create_component(
            project_id=test_project_id,
            name="DatabaseService",
        )
        assert isinstance(node_id1, str)
        
        # With underscores
        node_id2 = ims_graph_create_component(
            project_id=test_project_id,
            name="auth_service_v2",
        )
        assert isinstance(node_id2, str)
        
        # With dashes
        node_id3 = ims_graph_create_component(
            project_id=test_project_id,
            name="api-gateway",
        )
        assert isinstance(node_id3, str)
        
        # Mixed
        node_id4 = ims_graph_create_component(
            project_id=test_project_id,
            name="data_processor-v3",
        )
        assert isinstance(node_id4, str)

    def test_create_component_invalid_name_special_chars(self, test_project_id):
        """Test validation failure for component name with invalid characters."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_component(
                project_id=test_project_id,
                name="Auth@Service",  # @ is not allowed
            )
        
        assert "name must contain only alphanumeric characters, underscores, and dashes" in str(exc_info.value)

    def test_create_component_invalid_name_spaces(self, test_project_id):
        """Test validation failure for component name with spaces."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_component(
                project_id=test_project_id,
                name="Auth Service",  # Spaces not allowed
            )
        
        assert "name must contain only alphanumeric characters, underscores, and dashes" in str(exc_info.value)


class TestCrossToolIntegration:
    """Integration tests verifying multiple tools work together."""

    def test_create_multiple_nodes_different_types(self, test_project_id):
        """Test creating nodes of different types in sequence."""
        # Create a Decision
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use microservices architecture",
            rationale="Enables independent scaling and deployment of components",
            importance=0.85,
        )
        assert isinstance(decision_id, str)
        
        # Create a Component
        component_id = ims_graph_create_component(
            project_id=test_project_id,
            name="UserService",
            description="Handles user management operations",
        )
        assert isinstance(component_id, str)
        
        # Create a Feature
        feature_id = ims_graph_create_feature(
            project_id=test_project_id,
            description="Implement user registration workflow",
            priority="high",
        )
        assert isinstance(feature_id, str)
        
        # Create a Bug
        bug_id = ims_graph_create_bug(
            project_id=test_project_id,
            symptoms="User registration form validation fails for international phone numbers",
            severity="medium",
        )
        assert isinstance(bug_id, str)
        
        # All IDs should be unique
        all_ids = {decision_id, component_id, feature_id, bug_id}
        assert len(all_ids) == 4


class TestRelationshipCreation:
    """Integration tests for ims_graph_create_relationship tool (Task 2.2)."""

    def test_create_relationship_implements(self, test_project_id):
        """Test creating an 'implements' relationship between Feature and Decision."""
        # Create a Decision node
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use Redis for session state storage",
            rationale="Need atomic operations, TTL support, and multi-instance capability for session management",
        )
        
        # Create a Feature node
        feature_id = ims_graph_create_feature(
            project_id=test_project_id,
            description="Implement session management with Redis backend",
        )
        
        # Create implements relationship
        success = ims_graph_create_relationship(
            from_id=feature_id,
            rel_type="implements",
            to_id=decision_id,
        )
        
        assert success is True

    def test_create_relationship_blocks(self, test_project_id):
        """Test creating a 'blocks' relationship between Bug and Feature."""
        # Create a Bug node
        bug_id = ims_graph_create_bug(
            project_id=test_project_id,
            symptoms="Authentication middleware crashes on malformed JWT tokens",
            severity="critical",
        )
        
        # Create a Feature node
        feature_id = ims_graph_create_feature(
            project_id=test_project_id,
            description="Deploy authentication system to production",
        )
        
        # Create blocks relationship
        success = ims_graph_create_relationship(
            from_id=bug_id,
            rel_type="blocks",
            to_id=feature_id,
        )
        
        assert success is True

    def test_create_relationship_affects(self, test_project_id):
        """Test creating an 'affects' relationship between Decision and Component."""
        # Create a Decision node
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Switch from REST to GraphQL for API layer",
            rationale="GraphQL provides better flexibility for frontend teams and reduces over-fetching",
        )
        
        # Create a Component node
        component_id = ims_graph_create_component(
            project_id=test_project_id,
            name="APIGateway",
            description="Central API gateway handling all client requests",
        )
        
        # Create affects relationship
        success = ims_graph_create_relationship(
            from_id=decision_id,
            rel_type="affects",
            to_id=component_id,
        )
        
        assert success is True

    def test_create_relationship_depends_on(self, test_project_id):
        """Test creating a 'depends_on' relationship between Components."""
        # Create two Component nodes
        comp1_id = ims_graph_create_component(
            project_id=test_project_id,
            name="UserService",
            description="User management service",
        )
        
        comp2_id = ims_graph_create_component(
            project_id=test_project_id,
            name="AuthService",
            description="Authentication and authorization service",
        )
        
        # Create depends_on relationship
        success = ims_graph_create_relationship(
            from_id=comp1_id,
            rel_type="depends_on",
            to_id=comp2_id,
        )
        
        assert success is True

    def test_create_relationship_supersedes(self, test_project_id):
        """Test creating a 'supersedes' relationship between Decisions."""
        # Create old Decision
        old_decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use MongoDB for primary data storage",
            rationale="Document model was initially chosen for flexibility",
        )
        
        # Create new Decision
        new_decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use PostgreSQL for primary data storage",
            rationale="Relational model better fits our domain after requirements clarification",
        )
        
        # Create supersedes relationship
        success = ims_graph_create_relationship(
            from_id=new_decision_id,
            rel_type="supersedes",
            to_id=old_decision_id,
        )
        
        assert success is True

    def test_create_relationship_fixed_by(self, test_project_id):
        """Test creating a 'fixed_by' relationship between Bug and Decision."""
        # Create a Bug node
        bug_id = ims_graph_create_bug(
            project_id=test_project_id,
            symptoms="Race condition in session cleanup causes memory leaks",
            severity="high",
        )
        
        # Create a Decision node (the fix)
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Add distributed locking for session cleanup operations",
            rationale="Prevents concurrent cleanup operations from causing race conditions",
        )
        
        # Create fixed_by relationship
        success = ims_graph_create_relationship(
            from_id=bug_id,
            rel_type="fixed_by",
            to_id=decision_id,
        )
        
        assert success is True

    def test_create_relationship_with_properties(self, test_project_id):
        """Test creating a relationship with custom properties."""
        # Create two nodes
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Implement rate limiting for API endpoints",
            rationale="Protect against abuse and ensure fair resource usage",
        )
        
        component_id = ims_graph_create_component(
            project_id=test_project_id,
            name="RateLimiter",
            description="Rate limiting middleware",
        )
        
        # Create relationship with properties
        success = ims_graph_create_relationship(
            from_id=decision_id,
            rel_type="affects",
            to_id=component_id,
            properties={"confidence": 0.95, "impact_level": "high"},
        )
        
        assert success is True

    def test_create_relationship_invalid_type(self, test_project_id):
        """Test validation failure for invalid relationship type."""
        # Create two nodes
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Use Redis for caching",
            rationale="Fast in-memory cache improves performance",
        )
        
        component_id = ims_graph_create_component(
            project_id=test_project_id,
            name="CacheService",
        )
        
        # Try to create relationship with invalid type
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_relationship(
                from_id=decision_id,
                rel_type="invalid_type",
                to_id=component_id,
            )
        
        assert "rel_type must be one of" in str(exc_info.value)
        assert "implements" in str(exc_info.value)

    def test_create_multiple_relationships(self, test_project_id):
        """Test creating multiple relationships between different nodes."""
        # Create nodes
        decision_id = ims_graph_create_decision(
            project_id=test_project_id,
            text="Adopt event-driven architecture",
            rationale="Enables loose coupling and asynchronous processing",
        )
        
        comp1_id = ims_graph_create_component(
            project_id=test_project_id,
            name="EventBus",
        )
        
        comp2_id = ims_graph_create_component(
            project_id=test_project_id,
            name="UserEventProcessor",
        )
        
        feature_id = ims_graph_create_feature(
            project_id=test_project_id,
            description="Implement event-driven user notifications",
        )
        
        # Create multiple relationships
        success1 = ims_graph_create_relationship(
            from_id=decision_id,
            rel_type="affects",
            to_id=comp1_id,
        )
        
        success2 = ims_graph_create_relationship(
            from_id=comp2_id,
            rel_type="depends_on",
            to_id=comp1_id,
        )
        
        success3 = ims_graph_create_relationship(
            from_id=feature_id,
            rel_type="implements",
            to_id=decision_id,
        )
        
        assert success1 is True
        assert success2 is True
        assert success3 is True
