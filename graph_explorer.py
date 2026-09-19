"""
graph_explorer.py
=================
Interactive test program for the graph_lib library.

Usage
-----
    python graph_explorer.py                  # uses built-in sample dataset
    python graph_explorer.py --data data.json # load nodes/edges from JSON

JSON format
-----------
{
  "nodes": [
    {"node_id": 1, "name": "Python", "description": "Programming language"},
    ...
  ],
  "edges": [
    {"from_node_id": 1, "to_node_id": 2, "probability": 0.9},
    ...
  ]
}

Interaction
-----------
- Click a node to set it as the PRIME node (gold star).
- Ctrl+click a node to toggle it as a SEED node (green outline).
- Right-click a node to set it as the TARGET node (red diamond).
- The relatedness score (combined_relevance) updates automatically.
- Use the slider to adjust max DFS depth.
- Use the prime-weight slider to control how much the prime node dominates.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Optional, Set

import matplotlib
matplotlib.use("TkAgg")  # noqa: E402 — must come before pyplot import

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np
from matplotlib.widgets import Slider, Button

# ---------------------------------------------------------------------------
# Inline mock of GraphDB so traversal works without MongoDB
# ---------------------------------------------------------------------------

from graph_lib.models import GraphEdge, GraphNode
from graph_lib.traversal import combined_relevance


class _InMemoryDB:
    """Minimal drop-in replacement for GraphDB that stores data in dicts."""

    def __init__(
        self,
        nodes: List[GraphNode],
        edges: List[GraphEdge],
    ) -> None:
        self._nodes: Dict[int, GraphNode] = {n.node_id: n for n in nodes}
        # adjacency: from_id -> list[GraphEdge]
        self._adj: Dict[int, List[GraphEdge]] = {}
        for e in edges:
            self._adj.setdefault(e.from_node_id, []).append(e)

    # Methods used by traversal.py
    def get_edges_from(self, from_node_id: int) -> List[GraphEdge]:
        return list(self._adj.get(from_node_id, []))

    def get_node(self, node_id: int) -> Optional[GraphNode]:
        return self._nodes.get(node_id)

    def get_all_nodes(self) -> List[GraphNode]:
        return list(self._nodes.values())

    def get_all_edges(self) -> List[GraphEdge]:
        return [e for edges in self._adj.values() for e in edges]


# ---------------------------------------------------------------------------
# Sample dataset (used when no --data file is provided)
# ---------------------------------------------------------------------------

SAMPLE_NODES: List[GraphNode] = [
    GraphNode(1,  "Python",       "General-purpose programming language"),
    GraphNode(2,  "NumPy",        "Numerical computing library for Python"),
    GraphNode(3,  "Pandas",       "Data analysis and manipulation library"),
    GraphNode(4,  "Matplotlib",   "Plotting and visualisation library"),
    GraphNode(5,  "scikit-learn", "Machine-learning library for Python"),
    GraphNode(6,  "TensorFlow",   "Deep-learning framework by Google"),
    GraphNode(7,  "PyTorch",      "Deep-learning framework by Meta"),
    GraphNode(8,  "Jupyter",      "Interactive notebook environment"),
    GraphNode(9,  "SQL",          "Structured query language for databases"),
    GraphNode(10, "PostgreSQL",   "Open-source relational database"),
    GraphNode(11, "MongoDB",      "Document-oriented NoSQL database"),
    GraphNode(12, "Docker",       "Container platform"),
    GraphNode(13, "Kubernetes",   "Container orchestration system"),
    GraphNode(14, "REST API",     "Architectural style for web services"),
    GraphNode(15, "FastAPI",      "High-performance Python web framework"),
]

SAMPLE_EDGES: List[GraphEdge] = [
    # Python ecosystem
    GraphEdge(1,  2,  0.95),  # Python → NumPy
    GraphEdge(1,  3,  0.92),  # Python → Pandas
    GraphEdge(1,  4,  0.88),  # Python → Matplotlib
    GraphEdge(1,  5,  0.85),  # Python → scikit-learn
    GraphEdge(1,  6,  0.80),  # Python → TensorFlow
    GraphEdge(1,  7,  0.80),  # Python → PyTorch
    GraphEdge(1,  8,  0.90),  # Python → Jupyter
    GraphEdge(1,  15, 0.78),  # Python → FastAPI
    # Data science chain
    GraphEdge(2,  3,  0.90),  # NumPy → Pandas
    GraphEdge(2,  5,  0.82),  # NumPy → scikit-learn
    GraphEdge(3,  4,  0.75),  # Pandas → Matplotlib
    GraphEdge(3,  9,  0.60),  # Pandas → SQL
    GraphEdge(5,  6,  0.70),  # scikit-learn → TensorFlow
    GraphEdge(5,  7,  0.70),  # scikit-learn → PyTorch
    GraphEdge(6,  7,  0.85),  # TensorFlow → PyTorch
    # Databases
    GraphEdge(9,  10, 0.95),  # SQL → PostgreSQL
    GraphEdge(9,  11, 0.50),  # SQL → MongoDB
    GraphEdge(10, 14, 0.55),  # PostgreSQL → REST API
    GraphEdge(11, 14, 0.60),  # MongoDB → REST API
    GraphEdge(14, 15, 0.88),  # REST API → FastAPI
    # Infrastructure
    GraphEdge(12, 13, 0.92),  # Docker → Kubernetes
    GraphEdge(15, 12, 0.65),  # FastAPI → Docker
    GraphEdge(10, 12, 0.60),  # PostgreSQL → Docker
    # Notebook / exploration
    GraphEdge(8,  3,  0.82),  # Jupyter → Pandas
    GraphEdge(8,  4,  0.78),  # Jupyter → Matplotlib
]


# ---------------------------------------------------------------------------
# Colour / style constants
# ---------------------------------------------------------------------------

_NORMAL_COLOR = "#AED6F1"   # light blue
_PRIME_COLOR  = "#F9E79F"   # gold
_SEED_COLOR   = "#A9DFBF"   # light green
_TARGET_COLOR = "#F1948A"   # salmon red

_NODE_SIZE_BASE = 900
_EDGE_ALPHA     = 0.7


def _node_colors(
    node_ids: List[int],
    prime: Optional[int],
    seeds: Set[int],
    target: Optional[int],
) -> List[str]:
    colors = []
    for nid in node_ids:
        if nid == target:
            colors.append(_TARGET_COLOR)
        elif nid == prime:
            colors.append(_PRIME_COLOR)
        elif nid in seeds:
            colors.append(_SEED_COLOR)
        else:
            colors.append(_NORMAL_COLOR)
    return colors


# ---------------------------------------------------------------------------
# Main application class
# ---------------------------------------------------------------------------

class GraphExplorer:
    def __init__(self, nodes: List[GraphNode], edges: List[GraphEdge]) -> None:
        self.db    = _InMemoryDB(nodes, edges)
        self.nodes = nodes
        self.edges = edges

        # Selection state
        self.prime:        Optional[int] = None
        self.seeds:        Set[int]      = set()
        self.target:       Optional[int] = None
        self.max_depth:    int           = 5
        self.prime_weight: float         = 0.7

        # Build NetworkX directed graph
        self.G = nx.DiGraph()
        for n in nodes:
            self.G.add_node(n.node_id, label=n.name)
        for e in edges:
            self.G.add_edge(e.from_node_id, e.to_node_id, probability=e.probability)

        self.pos         = nx.spring_layout(self.G, seed=42, k=2.5)
        self.node_list   = [n.node_id for n in nodes]
        self.id_to_name  = {n.node_id: n.name        for n in nodes}
        self.id_to_desc  = {n.node_id: n.description for n in nodes}

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.fig = plt.figure(figsize=(14, 9), facecolor="#1E1E2E")
        self.fig.canvas.manager.set_window_title("Graph Explorer")

        # Axes layout
        self.ax_graph  = self.fig.add_axes([0.00, 0.15, 0.72, 0.85])
        self.ax_info   = self.fig.add_axes([0.73, 0.40, 0.26, 0.58])
        self.ax_legend = self.fig.add_axes([0.73, 0.15, 0.26, 0.23])

        # Control strip
        self.ax_depth_sl  = self.fig.add_axes([0.08, 0.06, 0.28, 0.03])
        self.ax_weight_sl = self.fig.add_axes([0.08, 0.02, 0.28, 0.03])
        self.ax_reset_btn = self.fig.add_axes([0.40, 0.02, 0.10, 0.07])

        # Sliders
        self.sl_depth = Slider(
            self.ax_depth_sl, "Max depth", 1, 10,
            valinit=self.max_depth, valstep=1,
            color="#5DADE2", track_color="#2E4057",
        )
        self.sl_weight = Slider(
            self.ax_weight_sl, "Prime weight", 0.0, 1.0,
            valinit=self.prime_weight, valstep=0.05,
            color="#F39C12", track_color="#2E4057",
        )
        for sl in (self.sl_depth, self.sl_weight):
            sl.label.set_color("white")
            sl.valtext.set_color("white")

        self.sl_depth.on_changed(self._on_slider)
        self.sl_weight.on_changed(self._on_slider)

        # Reset button
        self.btn_reset = Button(
            self.ax_reset_btn, "Reset",
            color="#922B21", hovercolor="#C0392B",
        )
        self.btn_reset.label.set_color("white")
        self.btn_reset.on_clicked(self._on_reset)

        self.fig.canvas.mpl_connect("button_press_event", self._on_click)

        self._draw()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        self.ax_graph.clear()
        self.ax_info.clear()
        self.ax_legend.clear()

        # Graph canvas styling
        self.ax_graph.set_facecolor("#12122A")
        self.ax_graph.set_title(
            "Click = prime  |  Ctrl+click = toggle seed  |  Right-click = target",
            color="white", fontsize=9, pad=6,
        )
        self.ax_graph.tick_params(left=False, bottom=False,
                                   labelleft=False, labelbottom=False)
        for spine in self.ax_graph.spines.values():
            spine.set_visible(False)

        # Edges — thickness and opacity driven by probability
        edge_list = list(self.G.edges())
        for u, v in edge_list:
            p = self.G[u][v]["probability"]
            nx.draw_networkx_edges(
                self.G, self.pos, edgelist=[(u, v)],
                ax=self.ax_graph,
                width=max(0.4, p * 7.0),
                alpha=max(0.25, p * _EDGE_ALPHA),
                edge_color="#7FB3D3",
                arrows=True,
                arrowstyle="-|>",
                arrowsize=14,
                connectionstyle="arc3,rad=0.08",
                min_source_margin=18,
                min_target_margin=18,
            )

        # Nodes
        colors     = _node_colors(self.node_list, self.prime, self.seeds, self.target)
        node_sizes = [
            _NODE_SIZE_BASE * (1.5 if nid in (self.prime, self.target)
                               else 1.2 if nid in self.seeds
                               else 1.0)
            for nid in self.node_list
        ]
        edge_colors = [
            "#F8C471" if nid == self.prime  else
            "#58D68D" if nid in self.seeds  else
            "#E74C3C" if nid == self.target else
            "#5D6D7E"
            for nid in self.node_list
        ]
        nx.draw_networkx_nodes(
            self.G, self.pos, ax=self.ax_graph,
            nodelist=self.node_list,
            node_color=colors,
            node_size=node_sizes,
            linewidths=2,
            edgecolors=edge_colors,
        )

        # Node labels
        nx.draw_networkx_labels(
            self.G, self.pos,
            labels={n.node_id: n.name for n in self.nodes},
            ax=self.ax_graph,
            font_size=7, font_color="#ECF0F1", font_weight="bold",
        )

        # Edge probability labels (only for edges >= 0.5 to avoid clutter)
        nx.draw_networkx_edge_labels(
            self.G, self.pos,
            edge_labels={
                (u, v): f"{self.G[u][v]['probability']:.2f}"
                for u, v in edge_list
                if self.G[u][v]["probability"] >= 0.5
            },
            ax=self.ax_graph,
            font_size=6, font_color="#BFC9CA",
            bbox=dict(boxstyle="round,pad=0.1", fc="#12122A", ec="none", alpha=0.6),
        )

        self._draw_info()
        self._draw_legend()
        self.fig.canvas.draw_idle()

    def _draw_info(self) -> None:
        ax = self.ax_info
        ax.set_facecolor("#1A1A2E")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title("Relatedness Score", color="white", fontsize=11, pad=8)

        prime_name  = self.id_to_name.get(self.prime,  "—")
        target_name = self.id_to_name.get(self.target, "—")
        seed_names  = [self.id_to_name[s] for s in sorted(self.seeds)] or ["—"]

        y = 0.88
        for label, value in [
            ("Prime",  prime_name),
            ("Target", target_name),
            ("Seeds",  ", ".join(seed_names)),
        ]:
            ax.text(0.05, y, f"{label}:  {value}",
                    color="white", fontsize=9, va="top", transform=ax.transAxes)
            y -= 0.10

        y -= 0.04
        score_text  = "—"
        score_color = "white"

        if self.prime is not None and self.target is not None:
            try:
                score = combined_relevance(
                    db=self.db,
                    prime_id=self.prime,
                    seed_ids=list(self.seeds),
                    candidate_id=self.target,
                    max_depth=self.max_depth,
                    prime_weight=self.prime_weight,
                )
                score_text  = f"{score:.4f}"
                score_color = (
                    "#58D68D" if score >= 0.6 else
                    "#F39C12" if score >= 0.3 else
                    "#E74C3C"
                )
            except Exception as exc:
                score_text  = f"Error: {exc}"
                score_color = "#E74C3C"

        ax.text(0.05, y, "Score:", color="white", fontsize=10,
                va="top", fontweight="bold", transform=ax.transAxes)
        ax.text(0.42, y, score_text, color=score_color, fontsize=18,
                va="top", fontweight="bold", transform=ax.transAxes)

        y -= 0.22
        ax.text(0.05, y,
                f"Depth: {self.max_depth}   Prime weight: {self.prime_weight:.2f}",
                color="#95A5A6", fontsize=8, va="top", transform=ax.transAxes)

        y -= 0.12
        for role, nid in [("Prime", self.prime), ("Target", self.target)]:
            if nid is not None:
                ax.text(0.05, y, f"{role}: {self.id_to_desc.get(nid, '')}",
                        color="#BFC9CA", fontsize=7.5, va="top",
                        transform=ax.transAxes, wrap=True)
                y -= 0.10

    def _draw_legend(self) -> None:
        ax = self.ax_legend
        ax.set_facecolor("#1A1A2E")
        ax.axis("off")
        ax.set_title("Legend", color="white", fontsize=9, pad=4)
        patches = [
            mpatches.Patch(color=_PRIME_COLOR,  label="Prime node  (click)"),
            mpatches.Patch(color=_SEED_COLOR,   label="Seed node   (Ctrl+click)"),
            mpatches.Patch(color=_TARGET_COLOR, label="Target node (right-click)"),
            mpatches.Patch(color=_NORMAL_COLOR, label="Unselected node"),
        ]
        ax.legend(
            handles=patches, loc="center", fontsize=7.5,
            facecolor="#1A1A2E", edgecolor="#5D6D7E",
            labelcolor="white", framealpha=0.9,
        )

    # ------------------------------------------------------------------
    # Hit testing — find nearest node to a click in data coordinates
    # ------------------------------------------------------------------

    def _nearest_node(self, xdata: float, ydata: float) -> Optional[int]:
        if xdata is None or ydata is None:
            return None
        click = np.array([xdata, ydata])
        best_id, best_dist = None, float("inf")
        for nid in self.node_list:
            dist = float(np.linalg.norm(click - np.array(self.pos[nid])))
            if dist < best_dist:
                best_dist, best_id = dist, nid
        return best_id if best_dist < 0.35 else None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_click(self, event) -> None:
        if event.inaxes is not self.ax_graph:
            return
        nid = self._nearest_node(event.xdata, event.ydata)
        if nid is None:
            return

        ctrl_held = event.key in ("control", "ctrl")

        if event.button == 1:       # left click
            if ctrl_held:
                self.seeds.discard(nid) if nid in self.seeds else self.seeds.add(nid)
            else:
                self.prime = None if self.prime == nid else nid
        elif event.button == 3:     # right click
            self.target = None if self.target == nid else nid

        self._draw()

    def _on_slider(self, _val) -> None:
        self.max_depth    = int(self.sl_depth.val)
        self.prime_weight = float(self.sl_weight.val)
        self._draw()

    def _on_reset(self, _event) -> None:
        self.prime  = None
        self.seeds  = set()
        self.target = None
        self._draw()

    def show(self) -> None:
        plt.show()


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def _load_json(path: str):
    with open(path) as fh:
        data = json.load(fh)
    nodes = [GraphNode(**n) for n in data["nodes"]]
    edges = [GraphEdge(**e) for e in data["edges"]]
    return nodes, edges


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive graph explorer for graph_lib."
    )
    parser.add_argument(
        "--data", metavar="FILE",
        help="Path to a JSON file with 'nodes' and 'edges' arrays. "
             "Uses built-in sample data if omitted.",
    )
    args = parser.parse_args()

    if args.data:
        nodes, edges = _load_json(args.data)
        print(f"Loaded {len(nodes)} nodes and {len(edges)} edges from {args.data}")
    else:
        nodes, edges = SAMPLE_NODES, SAMPLE_EDGES
        print("Using built-in sample dataset (15 nodes, 25 edges).")
        print("Pass --data <file.json> to load your own graph.\n")

    print("Controls:")
    print("  Left-click       → set PRIME node")
    print("  Ctrl+left-click  → toggle SEED node")
    print("  Right-click      → set TARGET node")
    print("  Reset button     → clear all selections")

    app = GraphExplorer(nodes, edges)
    app.show()


if __name__ == "__main__":
    main()
