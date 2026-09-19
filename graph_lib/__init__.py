"""
graph_lib — MongoDB-backed graph library with traversal utilities.

Modules:
    models   — GraphNode and GraphEdge dataclasses
    db       — MongoDB integration (read/write nodes and edges)
    traversal — DFS and multi-source distance functions
"""

from .models import GraphNode, GraphEdge
from .db import GraphDB
from .traversal import dfs_paths, multi_source_distances

__all__ = [
    "GraphNode",
    "GraphEdge",
    "GraphDB",
    "dfs_paths",
    "multi_source_distances",
]
