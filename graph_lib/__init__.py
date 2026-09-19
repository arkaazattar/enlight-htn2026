"""
graph_lib — MongoDB-backed graph library with traversal utilities.

Modules:
    models       — GraphNode and GraphEdge dataclasses
    db           — MongoDB integration (read/write nodes and edges)
    traversal    — Relevance scoring via Personalized PageRank
    graph_agent  — Gemini-powered ingestion and summarisation (GraphAgent)
"""
from .models import GraphNode, GraphEdge
from .db import GraphDB
from .traversal import combined_relevance, top_k_nodes
from .graph_agent import GraphAgent

__all__ = [
    "GraphNode",
    "GraphEdge",
    "GraphDB",
    "combined_relevance",
    "top_k_nodes",
    "GraphAgent",
]
