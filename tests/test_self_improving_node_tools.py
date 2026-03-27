"""Integration tests for self-improving node creation MCP tools (Task 2.2).

These tests verify that the MCP tools for creating Correction, Reflection, Pattern,
and Lesson nodes work correctly against a real IMS backend.

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
    ims_graph_create_correction,
    ims_graph_create_reflection,
    ims_graph_create_pattern,
    ims_graph_create_lesson,
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


class TestCorrectionNodeCreation:
    """Integration tests for ims_graph_create_correction tool."""

    def test_create_correction_global_scope(self, test_project_id):
        """Test creating a Correction node with global scope."""
        node_id = ims_graph_create_correction(
            text="Always use TypeScript strict mode in configuration files",
            context="TypeScript project setup and configuration",
            scope="global",
            confirmed=True,
            tags=["typescript", "config", "best-practice"],
        )
        
        # Should return a valid UUID string
        assert isinstance(node_id, str)
        assert len(node_id) == 36  # UUID format: 8-4-4-4-12
        assert "-" in node_id

    def test_create_correction_domain_scope(self, test_project_id):
        """Test creating a Correction node with domain scope."""
        node_id = ims_graph_create_correction(
            text="Always validate user input before database queries",
            context="Authentication and authorization workflows",
            scope="domain",
            domain="auth",
            confirmed=False,
            tags=["security", "auth", "input-validation"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_correction_project_scope(self, test_project_id):
        """Test creating a Correction node with project scope."""
        node_id = ims_graph_create_correction(
            text="Use Redis for session storage instead of file-based sessions",
            context="Session management in multi-instance deployment",
            scope="project",
            project_id=test_project_id,
            confirmed=True,
            tags=["redis", "sessions", "architecture"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_correction_text_too_short(self, test_project_id):
        """Test validation failure when text is too short."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_correction(
                text="Short",  # Less than 10 chars
                context="Valid context that is long enough",
                scope="global",
            )
        
        assert "text must be at least 10 characters" in str(exc_info.value)

    def test_create_correction_context_too_short(self, test_project_id):
        """Test validation failure when context is too short."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_correction(
                text="Valid correction text that is long enough",
                context="Short",  # Less than 10 chars
                scope="global",
            )
        
        assert "context must be at least 10 characters" in str(exc_info.value)

    def test_create_correction_invalid_scope(self, test_project_id):
        """Test validation failure for invalid scope."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_correction(
                text="Valid correction text",
                context="Valid context for correction",
                scope="invalid_scope",
            )
        
        assert "scope must be one of" in str(exc_info.value)

    def test_create_correction_project_scope_missing_project_id(self, test_project_id):
        """Test validation failure when project_id missing for project scope."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_correction(
                text="Valid correction text",
                context="Valid context for correction",
                scope="project",
                # project_id not provided
            )
        
        assert "project_id required when scope='project'" in str(exc_info.value)

    def test_create_correction_domain_scope_missing_domain(self, test_project_id):
        """Test validation failure when domain missing for domain scope."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_correction(
                text="Valid correction text",
                context="Valid context for correction",
                scope="domain",
                # domain not provided
            )
        
        assert "domain required when scope='domain'" in str(exc_info.value)


class TestReflectionNodeCreation:
    """Integration tests for ims_graph_create_reflection tool."""

    def test_create_reflection_minimal(self, test_project_id):
        """Test creating a Reflection node with minimal required fields."""
        node_id = ims_graph_create_reflection(
            task_type="implement_feature",
            lesson="Always consider rate limiting when implementing authentication endpoints to prevent brute force attacks",
            what_i_did="Implemented authentication endpoint",
            reflection="Security review revealed missing rate limiting",
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_reflection_full(self, test_project_id):
        """Test creating a Reflection node with all fields populated."""
        node_id = ims_graph_create_reflection(
            task_type="implement_auth_feature",
            lesson="Rate limiting should be implemented before deploying authentication features to production",
            what_i_did="Implemented OAuth2 flow with Redis session storage and JWT tokens",
            outcome="success",
            reflection="Initially forgot to add rate limiting middleware, had to revise implementation after security review",
            status="candidate",
            project_id=test_project_id,
            session_id="550e8400-e29b-41d4-a716-446655440000",
            tags=["reflection", "auth", "security", "rate-limiting"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_reflection_lesson_too_short(self, test_project_id):
        """Test validation failure when lesson is too short."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_reflection(
                task_type="fix_bug",
                lesson="Be careful",  # Less than 20 chars
                what_i_did="Fixed a bug",
                reflection="Noticed the bug",
            )
        
        assert "lesson must be at least 20 characters" in str(exc_info.value)

    def test_create_reflection_invalid_outcome(self, test_project_id):
        """Test validation failure for invalid outcome value."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_reflection(
                task_type="implement_feature",
                lesson="Valid lesson text that is long enough to pass validation",
                what_i_did="Implemented the feature",
                reflection="Reflected on the implementation",
                outcome="invalid_outcome",
            )
        
        assert "outcome must be one of" in str(exc_info.value)
        assert "success" in str(exc_info.value)

    def test_create_reflection_invalid_status(self, test_project_id):
        """Test validation failure for invalid status value."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_reflection(
                task_type="implement_feature",
                lesson="Valid lesson text that is long enough to pass validation",
                what_i_did="Implemented the feature",
                reflection="Reflected on the implementation",
                status="invalid_status",
            )
        
        assert "status must be one of" in str(exc_info.value)
        assert "candidate" in str(exc_info.value)


class TestPatternNodeCreation:
    """Integration tests for ims_graph_create_pattern tool."""

    def test_create_pattern_global_scope(self, test_project_id):
        """Test creating a Pattern node with global scope."""
        node_id = ims_graph_create_pattern(
            description="Always enable TypeScript strict mode in tsconfig.json for better type safety",
            scope="global",
            confidence=1.0,
            tags=["pattern", "typescript", "config"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_pattern_domain_scope(self, test_project_id):
        """Test creating a Pattern node with domain scope."""
        node_id = ims_graph_create_pattern(
            description="Use bcrypt with cost factor >= 12 for password hashing",
            scope="domain",
            domain="auth",
            confidence=0.95,
            tags=["pattern", "security", "auth"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_pattern_project_scope(self, test_project_id):
        """Test creating a Pattern node with project scope."""
        node_id = ims_graph_create_pattern(
            description="Use Redis for session state with TTL of 24 hours",
            scope="project",
            project_id=test_project_id,
            confidence=1.0,
            created_from=["550e8400-e29b-41d4-a716-446655440001"],
            tags=["pattern", "redis", "sessions"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_pattern_description_too_short(self, test_project_id):
        """Test validation failure when description is too short."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_pattern(
                description="Short",  # Less than 10 chars
                scope="global",
            )
        
        assert "description must be at least 10 characters" in str(exc_info.value)

    def test_create_pattern_invalid_scope(self, test_project_id):
        """Test validation failure for invalid scope."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_pattern(
                description="Valid pattern description",
                scope="invalid_scope",
            )
        
        assert "scope must be one of" in str(exc_info.value)

    def test_create_pattern_confidence_out_of_range(self, test_project_id):
        """Test validation failure when confidence is out of range."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_pattern(
                description="Valid pattern description",
                scope="global",
                confidence=1.5,  # Out of range
            )
        
        assert "confidence must be between 0.0 and 1.0" in str(exc_info.value)

    def test_create_pattern_project_scope_missing_project_id(self, test_project_id):
        """Test validation failure when project_id missing for project scope."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_pattern(
                description="Valid pattern description",
                scope="project",
                # project_id not provided
            )
        
        assert "project_id required when scope='project'" in str(exc_info.value)

    def test_create_pattern_domain_scope_missing_domain(self, test_project_id):
        """Test validation failure when domain missing for domain scope."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_pattern(
                description="Valid pattern description",
                scope="domain",
                # domain not provided
            )
        
        assert "domain required when scope='domain'" in str(exc_info.value)


class TestLessonNodeCreation:
    """Integration tests for ims_graph_create_lesson tool."""

    def test_create_lesson_minimal(self, test_project_id):
        """Test creating a Lesson node with minimal required fields."""
        node_id = ims_graph_create_lesson(
            text="Add rate limiting to all authentication endpoints before deployment to prevent brute force attacks",
            context="Authentication endpoint implementation",
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_lesson_full(self, test_project_id):
        """Test creating a Lesson node with all fields populated."""
        node_id = ims_graph_create_lesson(
            text="Implement rate limiting on all authentication endpoints with exponential backoff after failed attempts",
            context="Authentication endpoint security practices",
            category="security",
            applies_to=["550e8400-e29b-41d4-a716-446655440001"],
            verified=True,
            project_id=test_project_id,
            reflection_id="550e8400-e29b-41d4-a716-446655440002",
            tags=["lesson", "auth", "security", "rate-limiting"],
        )
        
        assert isinstance(node_id, str)
        assert len(node_id) == 36

    def test_create_lesson_text_too_short(self, test_project_id):
        """Test validation failure when text is too short."""
        with pytest.raises(ValueError) as exc_info:
            ims_graph_create_lesson(
                text="Be careful",  # Less than 20 chars
                context="General coding practices",
            )
        
        assert "text must be at least 20 characters" in str(exc_info.value)


class TestCrossToolIntegration:
    """Integration tests for workflows involving multiple self-improving nodes."""

    def test_create_correction_to_pattern_workflow(self, test_project_id):
        """Test creating a Correction and then a Pattern from it."""
        # Create correction
        correction_id = ims_graph_create_correction(
            text="Always use environment variables for configuration",
            context="Application configuration management",
            scope="global",
            confirmed=True,
            tags=["config", "best-practice"],
        )
        
        assert isinstance(correction_id, str)
        
        # Create pattern referencing the correction
        pattern_id = ims_graph_create_pattern(
            description="Use environment variables for all configuration values",
            scope="global",
            confidence=1.0,
            created_from=[correction_id],
            tags=["pattern", "config"],
        )
        
        assert isinstance(pattern_id, str)

    def test_create_reflection_to_lesson_workflow(self, test_project_id):
        """Test creating a Reflection and then a Lesson from it."""
        # Create reflection
        reflection_id = ims_graph_create_reflection(
            task_type="implement_api",
            lesson="Always add input validation before processing API requests to prevent injection attacks",
            what_i_did="Implemented REST API with database queries",
            reflection="Security review found missing input validation",
            outcome="partial",
            project_id=test_project_id,
        )
        
        assert isinstance(reflection_id, str)
        
        # Create lesson from reflection
        lesson_id = ims_graph_create_lesson(
            text="Implement input validation middleware at API gateway level before any business logic processing",
            context="API endpoint security best practices",
            category="security",
            verified=True,
            project_id=test_project_id,
            reflection_id=reflection_id,
            tags=["lesson", "security", "api"],
        )
        
        assert isinstance(lesson_id, str)
