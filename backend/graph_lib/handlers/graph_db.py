"""
graph_lib.db
~~~~~~~~~~~~
MongoDB integration for the graph library.

GraphDB wraps a pymongo database and exposes clean methods to persist and
retrieve :class:`~graph_lib.models.GraphNode` and
:class:`~graph_lib.models.GraphEdge` objects.

Collections used (created automatically on first write):
    nodes — one document per GraphNode
    edges — one document per GraphEdge

Indexes created on construction:
    nodes.node_id          — unique
    edges.(from_node_id, to_node_id) — unique compound
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database

from .models import GraphEdge, GraphNode


class GraphDB:
    """High-level interface for storing and loading graph data in MongoDB.

    Parameters:
        uri:      MongoDB connection URI (default: ``"mongodb://localhost:27017"``).
        db_name:  Name of the MongoDB database to use.
    """

    def __init__(
        self,
        uri: str = "mongodb://localhost:27017",
        db_name: str = "graph_db",
    ) -> None:
        self._client: MongoClient = MongoClient(uri)
        self._db: Database = self._client[db_name]
        self._nodes: Collection = self._db["nodes"]
        self._edges: Collection = self._db["edges"]
        self._ensure_indexes()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_indexes(self) -> None:
        """Create indexes if they don't already exist."""
        self._nodes.create_index([("node_id", ASCENDING)], unique=True)
        self._edges.create_index(
            [("from_node_id", ASCENDING), ("to_node_id", ASCENDING)],
            unique=True,
        )

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def add_node(self, node: GraphNode) -> GraphNode:
        """Insert *node* into the database.

        If a node with the same ``node_id`` already exists, it is replaced
        (upsert).  The returned object has ``mongo_id`` populated.

        Parameters:
            node: The :class:`~graph_lib.models.GraphNode` to persist.

        Returns:
            A new :class:`~graph_lib.models.GraphNode` with ``mongo_id`` set.
        """
        doc = node.to_document()
        result = self._nodes.find_one_and_replace(
            {"node_id": node.node_id},
            doc,
            upsert=True,
            return_document=True,  # returns the document after replacement
        )
        return GraphNode.from_document(result)

    def add_nodes(self, nodes: Iterable[GraphNode]) -> List[GraphNode]:
        """Convenience wrapper — insert multiple nodes.

        Parameters:
            nodes: An iterable of :class:`~graph_lib.models.GraphNode`.

        Returns:
            List of persisted nodes with ``mongo_id`` populated.
        """
        return [self.add_node(n) for n in nodes]

    def get_node(self, node_id: int) -> Optional[GraphNode]:
        """Fetch a single node by its integer ``node_id``.

        Returns:
            The matching :class:`~graph_lib.models.GraphNode`, or ``None`` if
            not found.
        """
        doc = self._nodes.find_one({"node_id": node_id})
        return GraphNode.from_document(doc) if doc else None

    def get_all_nodes(self) -> List[GraphNode]:
        """Return every node in the database."""
        return [GraphNode.from_document(d) for d in self._nodes.find()]

    def remove_node(self, node_id: int) -> None:
        """Remove a node and all its edges from the database."""
        self._nodes.delete_one({"node_id": node_id})
        self._edges.delete_many({
            "$or": [
                {"from_node_id": node_id},
                {"to_node_id": node_id}
            ]
        })

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        """Insert *edge* into the database.

        If an edge with the same ``(from_node_id, to_node_id)`` pair already
        exists, its probability is updated (upsert).  The returned object has
        ``mongo_id`` populated.

        Parameters:
            edge: The :class:`~graph_lib.models.GraphEdge` to persist.

        Returns:
            A new :class:`~graph_lib.models.GraphEdge` with ``mongo_id`` set.
        """
        doc = edge.to_document()
        result = self._edges.find_one_and_replace(
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
            },
            doc,
            upsert=True,
            return_document=True,
        )
        return GraphEdge.from_document(result)

    def add_edges(self, edges: Iterable[GraphEdge]) -> List[GraphEdge]:
        """Convenience wrapper — insert multiple edges.

        Parameters:
            edges: An iterable of :class:`~graph_lib.models.GraphEdge`.

        Returns:
            List of persisted edges with ``mongo_id`` populated.
        """
        return [self.add_edge(e) for e in edges]

    def get_edge(self, from_node_id: int, to_node_id: int) -> Optional[GraphEdge]:
        """Fetch the edge between two specific nodes.

        Returns:
            The matching :class:`~graph_lib.models.GraphEdge`, or ``None``.
        """
        doc = self._edges.find_one(
            {"from_node_id": from_node_id, "to_node_id": to_node_id}
        )
        return GraphEdge.from_document(doc) if doc else None

    def get_edges_from(self, from_node_id: int) -> List[GraphEdge]:
        """Return all edges that originate at *from_node_id*.

        Parameters:
            from_node_id: Integer ID of the source node.

        Returns:
            List of :class:`~graph_lib.models.GraphEdge` objects sorted by
            probability descending.
        """
        docs = self._edges.find(
            {"from_node_id": from_node_id},
            sort=[("probability", -1)],
        )
        return [GraphEdge.from_document(d) for d in docs]

    def get_edges_to(self, to_node_id: int) -> List[GraphEdge]:
        """Return all edges that terminate at *to_node_id*.

        Parameters:
            to_node_id: Integer ID of the destination node.

        Returns:
            List of :class:`~graph_lib.models.GraphEdge` objects sorted by
            probability descending.
        """
        docs = self._edges.find(
            {"to_node_id": to_node_id},
            sort=[("probability", -1)],
        )
        return [GraphEdge.from_document(d) for d in docs]

    def get_all_edges(self) -> List[GraphEdge]:
        """Return every edge in the database."""
        return [GraphEdge.from_document(d) for d in self._edges.find()]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying MongoDB connection."""
        self._client.close()

    def __enter__(self) -> "GraphDB":
        return self

    def __exit__(self, *_) -> None:
        self.close()
