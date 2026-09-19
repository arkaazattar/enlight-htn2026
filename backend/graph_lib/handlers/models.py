"""
graph_lib.models
~~~~~~~~~~~~~~~~
Plain Python dataclasses that represent the two core graph primitives.

GraphNode   — a vertex carrying an integer ID, a human-readable name, and a
              free-text description.
GraphEdge   — a directed edge from one node ID to another, carrying a
              probability in [0, 1] that the *to* node is related to the
              *from* node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GraphNode:
    """A vertex in the graph.

    Attributes:
        node_id:     Unique integer identifier for the object this node
                     represents.
        name:        Human-readable display name.
        description: Free-text description of the object.
        mongo_id:    The MongoDB ``_id`` string, populated after a round-trip
                     through :class:`~graph_lib.db.GraphDB`.  ``None`` when
                     the node has not yet been persisted.
    """

    node_id: int
    name: str
    description: str
    mongo_id: Optional[str] = field(default=None, compare=False, repr=False)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_document(self) -> dict:
        """Return a MongoDB-ready dictionary (excludes ``mongo_id``)."""
        return {
            "node_id": self.node_id,
            "name": self.name,
            "description": self.description,
        }

    @classmethod
    def from_document(cls, doc: dict) -> "GraphNode":
        """Construct a :class:`GraphNode` from a MongoDB document."""
        return cls(
            node_id=doc["node_id"],
            name=doc["name"],
            description=doc["description"],
            mongo_id=str(doc["_id"]) if "_id" in doc else None,
        )


@dataclass
class GraphEdge:
    """A directed, weighted edge between two nodes.

    The *weight* encodes the probability that ``to_node_id`` is related to
    ``from_node_id``.  It must lie in the closed interval ``[0, 1]``.

    Attributes:
        from_node_id: Integer ID of the source node.
        to_node_id:   Integer ID of the destination node.
        probability:  Float in ``[0, 1]``; higher means more likely related.
        mongo_id:     The MongoDB ``_id`` string, populated after persistence.
    """

    from_node_id: int
    to_node_id: int
    probability: float
    mongo_id: Optional[str] = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not (0.0 <= self.probability <= 1.0):
            raise ValueError(
                f"probability must be in [0, 1], got {self.probability!r}"
            )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_document(self) -> dict:
        """Return a MongoDB-ready dictionary (excludes ``mongo_id``)."""
        return {
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "probability": self.probability,
        }

    @classmethod
    def from_document(cls, doc: dict) -> "GraphEdge":
        """Construct a :class:`GraphEdge` from a MongoDB document."""
        return cls(
            from_node_id=doc["from_node_id"],
            to_node_id=doc["to_node_id"],
            probability=doc["probability"],
            mongo_id=str(doc["_id"]) if "_id" in doc else None,
        )
