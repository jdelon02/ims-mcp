"""Unit tests for GraphClient."""

import pytest
from unittest.mock import Mock, patch
import httpx

from app.graph_client import GraphClient


@pytest.fixture
def graph_client():
    """Create a GraphClient instance for testing."""
    return GraphClient(
        base_url="https://test.example.com",
        timeout=5.0,
        client_name="test-client",
        verify_ssl=True,
    )


class TestGraphClientInit:
    """Test GraphClient initialization."""

    def test_init_stores_config(self, graph_client):
        """Test that initialization stores configuration correctly."""
        assert graph_client.base_url == "https://test.example.com"
        assert graph_client.timeout == 5.0
        assert graph_client.client_name == "test-client"
        assert graph_client.verify_ssl is True


class TestCreateNode:
    """Test create_node method."""

    def test_create_node_success(self, graph_client):
        """Test successful node creation."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": "node-123"}
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            node_id = graph_client.create_node(
                node_type="Decision",
                properties={"text": "Use Redis", "project_id": "test-project"},
            )

        assert node_id == "node-123"

    def test_create_node_http_error(self, graph_client):
        """Test node creation with HTTP error."""
        mock_response = Mock()
        mock_response.status_code = 422
        mock_response.text = '{"detail": "Invalid node type"}'
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unprocessable Entity",
            request=Mock(),
            response=mock_response,
        )

        with patch.object(httpx.Client, "post", return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                graph_client.create_node(
                    node_type="InvalidType",
                    properties={},
                )
            
            # Should include response body in error message
            assert "422" in str(exc_info.value)
            assert "Invalid node type" in str(exc_info.value)


class TestCreateRelationship:
    """Test create_relationship method."""

    def test_create_relationship_success(self, graph_client):
        """Test successful relationship creation."""
        mock_response = Mock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = graph_client.create_relationship(
                from_id="node-1",
                rel_type="implements",
                to_id="node-2",
                properties={"confidence": 0.9},
            )

        assert result is True

    def test_create_relationship_no_properties(self, graph_client):
        """Test relationship creation without properties."""
        mock_response = Mock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response) as mock_post:
            result = graph_client.create_relationship(
                from_id="node-1",
                rel_type="affects",
                to_id="node-2",
            )

        assert result is True
        # Verify empty dict is used when properties=None
        call_args = mock_post.call_args
        assert call_args[1]["json"]["properties"] == {}


class TestImpactAnalysis:
    """Test impact_analysis method."""

    def test_impact_analysis_success(self, graph_client):
        """Test successful impact analysis."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "affected_components": ["comp-1", "comp-2"],
            "paths": [["decision-1", "affects", "comp-1"]],
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = graph_client.impact_analysis(
                entity_id="decision-123",
                entity_type="Decision",
            )

        assert "affected_components" in result
        assert len(result["affected_components"]) == 2


class TestBlockingAnalysis:
    """Test blocking_analysis method."""

    def test_blocking_analysis_success(self, graph_client):
        """Test successful blocking analysis."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "blocking_bugs": ["bug-1", "bug-2"],
            "paths": [["bug-1", "blocks", "feature-1"]],
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = graph_client.blocking_analysis(feature_id="feature-123")

        assert "blocking_bugs" in result


class TestArchitecturalDrift:
    """Test architectural_drift method."""

    def test_architectural_drift_success(self, graph_client):
        """Test successful architectural drift detection."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "drifted_components": ["comp-1"],
            "superseded_decisions": ["decision-old"],
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = graph_client.architectural_drift(project_id="test-project")

        assert "drifted_components" in result


class TestLookupPatterns:
    """Test lookup_patterns method."""

    def test_lookup_patterns_with_domain(self, graph_client):
        """Test pattern lookup with domain filter."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "patterns": ["pattern-1", "pattern-2"],
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = graph_client.lookup_patterns(
                component_name="auth-service",
                domain="security",
            )

        assert "patterns" in result

    def test_lookup_patterns_no_domain(self, graph_client):
        """Test pattern lookup without domain filter."""
        mock_response = Mock()
        mock_response.json.return_value = {"patterns": []}
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = graph_client.lookup_patterns(component_name="auth-service")

        assert "patterns" in result


class TestCorrectionsReady:
    """Test corrections_ready method."""

    def test_corrections_ready_with_project(self, graph_client):
        """Test finding corrections with project filter."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "corrections": ["correction-1"],
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = graph_client.corrections_ready(project_id="test-project")

        assert "corrections" in result

    def test_corrections_ready_no_project(self, graph_client):
        """Test finding corrections without project filter."""
        mock_response = Mock()
        mock_response.json.return_value = {"corrections": []}
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = graph_client.corrections_ready()

        assert "corrections" in result


class TestPromoteCorrection:
    """Test promote_correction method."""

    def test_promote_correction_success(self, graph_client):
        """Test successful correction promotion."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "pattern_id": "pattern-123",
            "success": True,
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            result = graph_client.promote_correction(correction_id="correction-123")

        assert result["success"] is True
        assert "pattern_id" in result


class TestErrorHandling:
    """Test error handling with detailed messages."""

    def test_error_includes_response_body(self, graph_client):
        """Test that errors include response body for debugging."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error details"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Internal Server Error",
            request=Mock(),
            response=mock_response,
        )

        with patch.object(httpx.Client, "post", return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                graph_client.create_node("Decision", {})
            
            error_msg = str(exc_info.value)
            assert "500" in error_msg
            assert "Internal server error details" in error_msg
