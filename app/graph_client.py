"""GraphClient for IMS backend graph operations.

This module provides a client wrapper for the IMS backend's graph/ontology
endpoints, enabling creation of nodes, relationships, and execution of
graph queries (impact analysis, blocking analysis, architectural drift, etc.).
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional, Literal
import httpx


NODE_TYPES = Literal[
    "Decision",
    "Bug",
    "Feature",
    "Component",
    "Correction",
    "Reflection",
    "Pattern",
    "Lesson"
]


class GraphClient:
    """Client for IMS graph operations.
    
    Wraps the IMS backend graph endpoints:
    - /graph/nodes/create
    - /graph/relationships/create
    - /graph/query/* (impact_analysis, blocking_analysis, etc.)
    - /graph/self_improve/* (corrections_ready, promote_correction)
    """

    def __init__(
        self,
        base_url: str,
        timeout: float,
        client_name: str,
        verify_ssl: bool,
    ) -> None:
        """Initialize GraphClient.
        
        Args:
            base_url: IMS backend base URL (e.g., https://ims.delongpa.com)
            timeout: HTTP timeout in seconds
            client_name: Client identifier for User-Agent header
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = base_url
        self.timeout = timeout
        self.client_name = client_name
        self.verify_ssl = verify_ssl

    def _client(self) -> httpx.Client:
        """Create a short-lived httpx.Client for a single operation."""
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "User-Agent": self.client_name,
                "Content-Type": "application/json",
            },
            verify=self.verify_ssl,
        )

    def _raise_for_status_with_body(self, resp: httpx.Response) -> None:
        """Raise for HTTP errors but include response body in exception."""
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = resp.text
            except Exception:  # noqa: BLE001
                body = "<unable to read response body>"

            raise httpx.HTTPStatusError(
                message=(
                    f"{exc}\n"
                    f"Response status: {resp.status_code}\n"
                    f"Response body: {body}"
                ),
                request=exc.request,
                response=resp,
            ) from exc

    def create_node(
        self,
        node_type: str,
        properties: Dict[str, Any],
    ) -> str:
        """Create ontology node.
        
        Args:
            node_type: One of the 8 node types (Decision, Bug, Feature, Component,
                      Correction, Reflection, Pattern, Lesson)
            properties: Node properties dict (e.g., {"text": "...", "project_id": "..."})
        
        Returns:
            Node ID (UUID string)
        
        Raises:
            httpx.HTTPStatusError: On HTTP errors (includes response body)
        """
        with self._client() as client:
            resp = client.post(
                "/graph/nodes/create",
                json={
                    "node_type": node_type,
                    "properties": properties,
                },
            )
            self._raise_for_status_with_body(resp)
            return resp.json()["id"]

    def create_relationship(
        self,
        from_id: str,
        rel_type: str,
        to_id: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Create relationship between nodes.
        
        Args:
            from_id: Source node ID
            rel_type: Relationship type (e.g., "implements", "blocks", "affects")
            to_id: Target node ID
            properties: Optional relationship properties
        
        Returns:
            True if successful
        
        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        with self._client() as client:
            resp = client.post(
                "/graph/relationships/create",
                json={
                    "from_id": from_id,
                    "rel_type": rel_type,
                    "to_id": to_id,
                    "properties": properties or {},
                },
            )
            self._raise_for_status_with_body(resp)
            return resp.json()["success"]

    def impact_analysis(
        self,
        entity_id: str,
        entity_type: str,
    ) -> Dict[str, Any]:
        """Run impact analysis query.
        
        Find what would be affected by changes to the given entity.
        
        Args:
            entity_id: Node ID to analyze
            entity_type: Node type (e.g., "Decision", "Component")
        
        Returns:
            Dict with affected entities, relationship paths, etc.
        
        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        with self._client() as client:
            resp = client.post(
                "/graph/query/impact_analysis",
                json={
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                },
            )
            self._raise_for_status_with_body(resp)
            return resp.json()

    def blocking_analysis(
        self,
        feature_id: str,
    ) -> Dict[str, Any]:
        """What bugs block this feature?
        
        Args:
            feature_id: Feature node ID
        
        Returns:
            Dict with blocking bugs and paths
        
        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        with self._client() as client:
            resp = client.post(
                "/graph/query/blocking_analysis",
                json={"feature_id": feature_id},
            )
            self._raise_for_status_with_body(resp)
            return resp.json()

    def architectural_drift(
        self,
        project_id: str,
    ) -> Dict[str, Any]:
        """Detect components following superseded decisions.
        
        Args:
            project_id: Project identifier
        
        Returns:
            Dict with drifted components and superseded decisions
        
        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        with self._client() as client:
            resp = client.post(
                "/graph/query/architectural_drift",
                json={"project_id": project_id},
            )
            self._raise_for_status_with_body(resp)
            return resp.json()

    def lookup_patterns(
        self,
        component_name: str,
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Find patterns applicable to component.
        
        Args:
            component_name: Component name to look up
            domain: Optional domain filter (e.g., "auth", "caching")
        
        Returns:
            Dict with applicable patterns
        
        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        with self._client() as client:
            resp = client.post(
                "/graph/query/patterns",
                json={
                    "component_name": component_name,
                    "domain": domain,
                },
            )
            self._raise_for_status_with_body(resp)
            return resp.json()

    def corrections_ready(
        self,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Find corrections ready for promotion.
        
        Args:
            project_id: Optional project filter
        
        Returns:
            Dict with corrections ready for promotion to patterns
        
        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        with self._client() as client:
            resp = client.post(
                "/graph/self_improve/corrections_ready",
                json={"project_id": project_id},
            )
            self._raise_for_status_with_body(resp)
            return resp.json()

    def promote_correction(
        self,
        correction_id: str,
    ) -> Dict[str, Any]:
        """Promote correction to pattern.
        
        Args:
            correction_id: Correction node ID
        
        Returns:
            Dict with promotion result (new Pattern node ID, etc.)
        
        Raises:
            httpx.HTTPStatusError: On HTTP errors
        """
        with self._client() as client:
            resp = client.post(
                "/graph/self_improve/promote_correction",
                json={"correction_id": correction_id},
            )
            self._raise_for_status_with_body(resp)
            return resp.json()
