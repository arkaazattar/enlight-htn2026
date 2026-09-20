"""Graph controller — simple node lookup and field updates by node ID."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.graph_lib.handlers.graph_db import GraphDB
from backend.graph_lib.handlers.models import GraphNode


# ---------------------------------------------------------------------------
# Shared DB instance (injected at startup by backend/main.py)
# ---------------------------------------------------------------------------

graph_db: GraphDB | None = None


def set_graph_db(db: GraphDB) -> None:
    global graph_db
    graph_db = db


def get_graph_db() -> GraphDB | None:
    return graph_db


def get_db() -> GraphDB:
    if not graph_db:
        raise HTTPException(status_code=503, detail="Graph database not connected")
    return graph_db


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class UpdateName(BaseModel):
    name: str

class UpdateDescription(BaseModel):
    description: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

graph_router = APIRouter(prefix="/graph", tags=["Graph"])


@graph_router.get("/{node_id}")
def get_node(node_id: int):
    """Get a node's name and description by ID."""
    node = get_db().get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return {"node_id": node.node_id, "name": node.name, "description": node.description}


@graph_router.patch("/{node_id}/name")
def update_name(node_id: int, body: UpdateName):
    """Update a node's name."""
    db = get_db()
    node = db.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    updated = db.add_node(GraphNode(node_id=node_id, name=body.name, description=node.description))
    return {"node_id": updated.node_id, "name": updated.name, "description": updated.description}


@graph_router.patch("/{node_id}/description")
def update_description(node_id: int, body: UpdateDescription):
    """Update a node's description."""
    db = get_db()
    node = db.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    updated = db.add_node(GraphNode(node_id=node_id, name=node.name, description=body.description))
    return {"node_id": updated.node_id, "name": updated.name, "description": updated.description}

@graph_router.get("/{node_id}/closest")
def get_closest_nodes(node_id: int, limit: int = 2):
    """Get the closest related nodes based on probability."""
    db = get_db()
    edges = db.get_edges_from(node_id) + db.get_edges_to(node_id)
    
    related = []
    seen = set()
    
    # Sort edges by probability descending
    sorted_edges = sorted(edges, key=lambda x: x.probability, reverse=True)
    
    for e in sorted_edges:
        if e.probability <= 0:
            continue
            
        other_id = e.to_node_id if e.from_node_id == node_id else e.from_node_id
        if other_id in seen:
            continue
            
        seen.add(other_id)
        other_node = db.get_node(other_id)
        
        if other_node:
            person_hex = hex(other_id)[2:]
            related.append({
                "node_id": other_id,
                "person_id": person_hex,
                "name": other_node.name,
                "probability": e.probability
            })
            
        if len(related) >= limit:
            break
            
    return {"related": related}
