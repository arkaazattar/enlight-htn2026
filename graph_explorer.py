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
- Click a node to set it as the PRIME node (gold).
- Ctrl+click a node to toggle it as a SEED node (green).
- Right-click a node to set it as the TARGET node (red).
  - With a target set:  the info panel shows the combined_relevance score.
  - Without a target:   the info panel shows the top-k most relevant nodes,
                        ranked by score, and those nodes are highlighted
                        on the graph in a purple-to-white gradient.
- Use the sliders to adjust max DFS depth, prime weight, and k.
- Reset button clears all selections.
"""

from __future__ import annotations

import argparse
import json
from typing import Dict, List, Optional, Set, Tuple

import matplotlib
matplotlib.use("TkAgg")  # noqa: E402

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import networkx as nx
import numpy as np
from matplotlib.widgets import Slider, Button

from backend.graph_lib.handlers.models import GraphEdge, GraphNode
from backend.graph_lib.handlers.traversal import combined_relevance, top_k_nodes


# ---------------------------------------------------------------------------
# In-memory DB mock (no MongoDB required for the explorer)
# ---------------------------------------------------------------------------

class _InMemoryDB:
    """Drop-in replacement for GraphDB backed by plain dicts."""

    def __init__(self, nodes: List[GraphNode], edges: List[GraphEdge]) -> None:
        self._nodes: Dict[int, GraphNode] = {n.node_id: n for n in nodes}
        self._edges = list(edges)
        self._adj:   Dict[int, List[GraphEdge]] = {}
        for e in edges:
            self._adj.setdefault(e.from_node_id, []).append(e)
            self._adj.setdefault(e.to_node_id, []).append(e)

    def get_edges_from(self, from_node_id: int) -> List[GraphEdge]:
        return list(self._adj.get(from_node_id, []))

    def get_node(self, node_id: int) -> Optional[GraphNode]:
        return self._nodes.get(node_id)

    def get_all_nodes(self) -> List[GraphNode]:
        return list(self._nodes.values())

    def get_all_edges(self) -> List[GraphEdge]:
        return list(self._edges)


# ---------------------------------------------------------------------------
# Sample dataset
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
    GraphEdge(1,  2,  0.95),
    GraphEdge(1,  3,  0.92),
    GraphEdge(1,  4,  0.88),
    GraphEdge(1,  5,  0.85),
    GraphEdge(1,  6,  0.80),
    GraphEdge(1,  7,  0.80),
    GraphEdge(1,  8,  0.90),
    GraphEdge(1,  15, 0.78),
    GraphEdge(2,  3,  0.90),
    GraphEdge(2,  5,  0.82),
    GraphEdge(3,  4,  0.75),
    GraphEdge(3,  9,  0.60),
    GraphEdge(5,  6,  0.70),
    GraphEdge(5,  7,  0.70),
    GraphEdge(6,  7,  0.85),
    GraphEdge(9,  10, 0.95),
    GraphEdge(9,  11, 0.50),
    GraphEdge(10, 14, 0.55),
    GraphEdge(11, 14, 0.60),
    GraphEdge(14, 15, 0.88),
    GraphEdge(12, 13, 0.92),
    GraphEdge(15, 12, 0.65),
    GraphEdge(10, 12, 0.60),
    GraphEdge(8,  3,  0.82),
    GraphEdge(8,  4,  0.78),
]


# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------

_NORMAL_COLOR = "#AED6F1"
_PRIME_COLOR  = "#F9E79F"
_SEED_COLOR   = "#A9DFBF"
_TARGET_COLOR = "#F1948A"
_TOPK_COLOR   = "#C39BD3"   # purple tint for top-k highlighted nodes

_NODE_SIZE_BASE = 900
_EDGE_ALPHA     = 0.7

# Colormap used to shade top-k nodes: rank-1 is most saturated purple,
# rank-k fades toward the normal node colour.
_TOPK_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "topk", ["#7D3C98", "#D7BDE2"]
)


def _score_to_color(score: float, max_score: float = 1.0) -> str:
    """Green / orange / red based on score relative to max_score."""
    if max_score > 0:
        relative = score / max_score
    else:
        relative = 0.0
    if relative >= 0.6:
        return "#58D68D"
    if relative >= 0.3:
        return "#F39C12"
    return "#E74C3C"


def _node_colors(
    node_list: List[int],
    prime: Optional[int],
    seeds: Set[int],
    target: Optional[int],
    topk_ids: List[int],          # ordered best→worst
    topk_scores: Dict[int, float],
) -> List[str]:
    """Return a fill colour for every node in node_list."""
    k = len(topk_ids)
    colors = []
    for nid in node_list:
        if nid == target:
            colors.append(_TARGET_COLOR)
        elif nid == prime:
            colors.append(_PRIME_COLOR)
        elif nid in seeds:
            colors.append(_SEED_COLOR)
        elif nid in topk_scores:
            rank = topk_ids.index(nid)          # 0-based
            t    = rank / max(k - 1, 1)         # 0 = best, 1 = worst
            rgba = _TOPK_CMAP(1.0 - t)          # invert so best = darkest
            colors.append(mcolors.to_hex(rgba))
        else:
            colors.append(_NORMAL_COLOR)
    return colors


# ---------------------------------------------------------------------------
# Main application
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
        self.k:            int           = 5

        # Cached top-k results (recomputed on every state change)
        self._topk_results: List[Tuple[float, int]] = []

        # NetworkX graph
        self.G = nx.Graph()
        for n in nodes:
            self.G.add_node(n.node_id, label=n.name)
        for e in edges:
            self.G.add_edge(e.from_node_id, e.to_node_id, probability=e.probability)

        self.pos        = nx.spring_layout(self.G, seed=42, k=2.5)
        self.node_list  = [n.node_id for n in nodes]
        self.id_to_name = {n.node_id: n.name        for n in nodes}
        self.id_to_desc = {n.node_id: n.description for n in nodes}

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.fig = plt.figure(figsize=(15, 9), facecolor="#1E1E2E")
        self.fig.canvas.manager.set_window_title("Graph Explorer")

        # Main graph canvas
        self.ax_graph  = self.fig.add_axes([0.00, 0.15, 0.72, 0.85])
        # Info panel (right side)
        self.ax_info   = self.fig.add_axes([0.73, 0.40, 0.26, 0.58])
        # Legend (bottom-right)
        self.ax_legend = self.fig.add_axes([0.73, 0.15, 0.26, 0.23])

        # Control strip — three sliders + reset button
        self.ax_depth_sl  = self.fig.add_axes([0.06, 0.07, 0.22, 0.03])
        self.ax_weight_sl = self.fig.add_axes([0.06, 0.03, 0.22, 0.03])
        self.ax_k_sl      = self.fig.add_axes([0.32, 0.05, 0.18, 0.03])
        self.ax_reset_btn = self.fig.add_axes([0.53, 0.02, 0.10, 0.07])

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
        self.sl_k = Slider(
            self.ax_k_sl, "Top k", 1, min(20, len(self.nodes)),
            valinit=self.k, valstep=1,
            color="#A569BD", track_color="#2E4057",
        )
        for sl in (self.sl_depth, self.sl_weight, self.sl_k):
            sl.label.set_color("white")
            sl.valtext.set_color("white")

        self.sl_depth.on_changed(self._on_slider)
        self.sl_weight.on_changed(self._on_slider)
        self.sl_k.on_changed(self._on_slider)

        self.btn_reset = Button(
            self.ax_reset_btn, "Reset",
            color="#922B21", hovercolor="#C0392B",
        )
        self.btn_reset.label.set_color("white")
        self.btn_reset.on_clicked(self._on_reset)

        self.fig.canvas.mpl_connect("button_press_event", self._on_click)

        self._draw()

    # ------------------------------------------------------------------
    # Top-k computation
    # ------------------------------------------------------------------

    def _compute_topk(self) -> None:
        """Recompute and cache top-k results from the current state."""
        if self.prime is None:
            self._topk_results = []
            return
        try:
            self._topk_results = top_k_nodes(
                db=self.db,
                prime_id=self.prime,
                seed_ids=list(self.seeds),
                k=self.k,
                max_depth=self.max_depth,
                prime_weight=self.prime_weight,
            )
        except Exception:
            self._topk_results = []

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        # Recompute top-k whenever something changes
        self._compute_topk()

        topk_scores: Dict[int, float] = {nid: s for s, nid in self._topk_results}
        topk_ids:    List[int]        = [nid for _, nid in self._topk_results]

        self.ax_graph.clear()
        self.ax_info.clear()
        self.ax_legend.clear()

        # ---- graph canvas ----
        self.ax_graph.set_facecolor("#12122A")
        self.ax_graph.set_title(
            "Click = prime  |  Ctrl+click = toggle seed  |  Right-click = target",
            color="white", fontsize=9, pad=6,
        )
        self.ax_graph.tick_params(left=False, bottom=False,
                                   labelleft=False, labelbottom=False)
        for spine in self.ax_graph.spines.values():
            spine.set_visible(False)

        # Edges
        for u, v in self.G.edges():
            p = self.G[u][v]["probability"]
            nx.draw_networkx_edges(
                self.G, self.pos, edgelist=[(u, v)],
                ax=self.ax_graph,
                width=max(0.4, p * 7.0),
                alpha=max(0.25, p * _EDGE_ALPHA),
                edge_color="#7FB3D3",
                arrows=False,
            )

        # Nodes
        colors = _node_colors(
            self.node_list, self.prime, self.seeds,
            self.target, topk_ids, topk_scores,
        )
        node_sizes = [
            _NODE_SIZE_BASE * (
                1.5 if nid in (self.prime, self.target) else
                1.3 if nid in topk_scores               else
                1.2 if nid in self.seeds                else
                1.0
            )
            for nid in self.node_list
        ]
        border_colors = [
            "#F8C471" if nid == self.prime  else
            "#58D68D" if nid in self.seeds  else
            "#E74C3C" if nid == self.target else
            "#A569BD" if nid in topk_scores else
            "#5D6D7E"
            for nid in self.node_list
        ]
        nx.draw_networkx_nodes(
            self.G, self.pos, ax=self.ax_graph,
            nodelist=self.node_list,
            node_color=colors,
            node_size=node_sizes,
            linewidths=2,
            edgecolors=border_colors,
        )

        # Rank badges on top-k nodes (small number drawn at node position)
        for rank, (score, nid) in enumerate(self._topk_results, start=1):
            x, y = self.pos[nid]
            self.ax_graph.text(
                x, y + 0.07, f"#{rank}",
                ha="center", va="bottom",
                fontsize=6.5, fontweight="bold",
                color="white",
                bbox=dict(boxstyle="round,pad=0.15", fc="#7D3C98",
                          ec="none", alpha=0.85),
            )

        # Node name labels
        nx.draw_networkx_labels(
            self.G, self.pos,
            labels={n.node_id: n.name for n in self.nodes},
            ax=self.ax_graph,
            font_size=7, font_color="#ECF0F1", font_weight="bold",
        )

        # Edge probability labels (≥ 0.5 only)
        nx.draw_networkx_edge_labels(
            self.G, self.pos,
            edge_labels={
                (u, v): f"{self.G[u][v]['probability']:.2f}"
                for u, v in self.G.edges()
                if self.G[u][v]["probability"] >= 0.5
            },
            ax=self.ax_graph,
            font_size=6, font_color="#BFC9CA",
            bbox=dict(boxstyle="round,pad=0.1", fc="#12122A", ec="none", alpha=0.6),
        )

        self._draw_info(topk_ids, topk_scores)
        self._draw_legend()
        self.fig.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Info panel
    # ------------------------------------------------------------------

    def _draw_info(
        self,
        topk_ids: List[int],
        topk_scores: Dict[int, float],
    ) -> None:
        ax = self.ax_info
        ax.set_facecolor("#1A1A2E")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        prime_name = self.id_to_name.get(self.prime,  "—")
        seed_names = [self.id_to_name[s] for s in sorted(self.seeds)] or ["—"]

        # ---- header: always show prime / seeds ----
        y = 0.95
        ax.text(0.05, y, f"Prime:  {prime_name}",
                color="white", fontsize=9, va="top", transform=ax.transAxes)
        y -= 0.09
        # Wrap long seed lists
        seed_str = ", ".join(seed_names)
        ax.text(0.05, y, f"Seeds:  {seed_str}",
                color="white", fontsize=9, va="top", transform=ax.transAxes,
                wrap=True)
        y -= 0.09
        ax.text(0.05, y,
                f"Depth: {self.max_depth}   Weight: {self.prime_weight:.2f}   k: {self.k}",
                color="#95A5A6", fontsize=8, va="top", transform=ax.transAxes)
        y -= 0.07

        ax.axhline(y, color="#3D3D5C", linewidth=0.8, xmin=0.03, xmax=0.97)
        y -= 0.04

        # ---- branch: target set → single score; no target → top-k list ----
        if self.target is not None:
            target_name = self.id_to_name.get(self.target, "—")
            ax.set_title("Relatedness Score", color="white", fontsize=11, pad=8)
            ax.text(0.05, y, f"Target: {target_name}",
                    color=_TARGET_COLOR, fontsize=9, fontweight="bold",
                    va="top", transform=ax.transAxes)
            y -= 0.12

            score_text  = "—"
            score_color = "white"
            if self.prime is not None:
                try:
                    score = combined_relevance(
                        db=self.db,
                        prime_id=self.prime,
                        seed_ids=list(self.seeds),
                        candidate_id=self.target,
                        max_depth=self.max_depth,
                        prime_weight=self.prime_weight,
                    )
                    # Normalise against the prime node's own PPR score so the
                    # colour thresholds are meaningful regardless of graph size.
                    prime_score = combined_relevance(
                        db=self.db,
                        prime_id=self.prime,
                        seed_ids=list(self.seeds),
                        candidate_id=self.prime,
                        max_depth=self.max_depth,
                        prime_weight=self.prime_weight,
                    )
                    score_text  = f"{score:.4f}"
                    score_color = _score_to_color(score, max_score=max(prime_score, score))
                except Exception as exc:
                    score_text  = f"Err: {exc}"
                    score_color = "#E74C3C"

            ax.text(0.05, y, "Score:", color="white", fontsize=10,
                    fontweight="bold", va="top", transform=ax.transAxes)
            ax.text(0.42, y, score_text, color=score_color, fontsize=20,
                    fontweight="bold", va="top", transform=ax.transAxes)
            y -= 0.18

            # Descriptions
            for role, nid in [("Prime", self.prime), ("Target", self.target)]:
                if nid is not None:
                    ax.text(0.05, y, f"{role}: {self.id_to_desc.get(nid, '')}",
                            color="#BFC9CA", fontsize=7.5, va="top",
                            transform=ax.transAxes, wrap=True)
                    y -= 0.09

        else:
            # ---- Top-k ranked list ----
            ax.set_title(f"Top {self.k} Related Nodes", color="white",
                         fontsize=11, pad=8)

            if self.prime is None:
                ax.text(0.5, 0.5, "Select a prime node\nto see top-k results",
                        color="#95A5A6", fontsize=10, ha="center", va="center",
                        transform=ax.transAxes)
                return

            if not topk_ids:
                ax.text(0.5, 0.5, "No reachable candidates\nat this depth",
                        color="#95A5A6", fontsize=10, ha="center", va="center",
                        transform=ax.transAxes)
                return

            # Column headers
            ax.text(0.05, y, "Rank  Node", color="#95A5A6",
                    fontsize=8, va="top", transform=ax.transAxes,
                    fontweight="bold")
            ax.text(0.80, y, "Score", color="#95A5A6",
                    fontsize=8, va="top", transform=ax.transAxes,
                    fontweight="bold")
            y -= 0.06
            ax.axhline(y + 0.01, color="#3D3D5C", linewidth=0.6,
                       xmin=0.03, xmax=0.97)

            row_height = min(0.08, (y - 0.02) / max(len(topk_ids), 1))
            max_score  = topk_scores[topk_ids[0]] if topk_ids else 1.0
            for rank, nid in enumerate(topk_ids, start=1):
                score      = topk_scores[nid]
                name       = self.id_to_name.get(nid, str(nid))
                # Normalise bar width relative to the top-ranked score.
                bar_width  = (score / max_score) * 0.55 if max_score > 0 else 0
                bar_color  = _score_to_color(score, max_score=max_score)

                # Background score bar
                ax.barh(
                    y - row_height * 0.4,
                    bar_width, height=row_height * 0.7,
                    left=0.05, color=bar_color, alpha=0.20,
                    align="center",
                )

                # Rank badge colour mirrors the node fill
                t         = (rank - 1) / max(self.k - 1, 1)
                badge_rgb = _TOPK_CMAP(1.0 - t)
                badge_hex = mcolors.to_hex(badge_rgb)

                ax.text(0.05, y, f"#{rank}", color=badge_hex,
                        fontsize=8, fontweight="bold",
                        va="top", transform=ax.transAxes)
                ax.text(0.18, y, name, color="white",
                        fontsize=8, va="top", transform=ax.transAxes)
                ax.text(0.80, y, f"{score:.3f}", color=bar_color,
                        fontsize=8, fontweight="bold",
                        va="top", transform=ax.transAxes)

                y -= row_height

    # ------------------------------------------------------------------
    # Legend
    # ------------------------------------------------------------------

    def _draw_legend(self) -> None:
        ax = self.ax_legend
        ax.set_facecolor("#1A1A2E")
        ax.axis("off")
        ax.set_title("Legend", color="white", fontsize=9, pad=4)
        patches = [
            mpatches.Patch(color=_PRIME_COLOR,  label="Prime node  (click)"),
            mpatches.Patch(color=_SEED_COLOR,   label="Seed node   (Ctrl+click)"),
            mpatches.Patch(color=_TARGET_COLOR, label="Target node (right-click)"),
            mpatches.Patch(color=_TOPK_COLOR,   label="Top-k node  (no target)"),
            mpatches.Patch(color=_NORMAL_COLOR, label="Unselected node"),
        ]
        ax.legend(
            handles=patches, loc="center", fontsize=7.5,
            facecolor="#1A1A2E", edgecolor="#5D6D7E",
            labelcolor="white", framealpha=0.9,
        )

    # ------------------------------------------------------------------
    # Hit testing
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

        if event.button == 1:
            if ctrl_held:
                self.seeds.discard(nid) if nid in self.seeds else self.seeds.add(nid)
            else:
                self.prime = None if self.prime == nid else nid
        elif event.button == 3:
            self.target = None if self.target == nid else nid

        self._draw()

    def _on_slider(self, _val) -> None:
        self.max_depth    = int(self.sl_depth.val)
        self.prime_weight = float(self.sl_weight.val)
        self.k            = int(self.sl_k.val)
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
        help="JSON file with 'nodes' and 'edges' arrays. "
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
    print("  Right-click      → set TARGET node (shows score)")
    print("  No target        → top-k ranked list shown instead")
    print("  Reset button     → clear all selections")

    app = GraphExplorer(nodes, edges)
    app.show()


if __name__ == "__main__":
    main()
