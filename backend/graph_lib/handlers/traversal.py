"""
graph_lib.traversal
~~~~~~~~~~~~~~~~~~~
Graph traversal and relevance utilities.

Public API
----------
combined_relevance(db, prime_id, seed_ids, candidate_id, ...)
    Score how relevant a single candidate node is given a prime and seeds,
    using Personalized PageRank.

top_k_nodes(db, prime_id, seed_ids, k, ...)
    Return the k most relevant nodes using Personalized PageRank.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

import networkx as nx

from .graph_db import GraphDB


# ---------------------------------------------------------------------------
# Internal helper — builds a weighted undirected graph from the database
# ---------------------------------------------------------------------------

def _build_graph(db: GraphDB) -> nx.Graph:
    """Return a weighted :class:`nx.Graph` from all nodes and edges in *db*.

    Edge weights are the stored probabilities, floored at ``1e-6`` so that
    zero-probability edges still participate weakly in random walks.
    """
    G = nx.Graph()
    for node in db.get_all_nodes():
        G.add_node(node.node_id)
    for edge in db.get_all_edges():
        G.add_edge(
            edge.from_node_id,
            edge.to_node_id,
            weight=max(edge.probability, 1e-6),
        )
    return G


def _personalisation(
    G: nx.Graph,
    prime_id: int,
    seed_ids: List[int],
    prime_weight: float,
) -> Dict[int, float]:
    """Build a PPR restart distribution over nodes in *G*.

    The prime node receives *prime_weight* of the restart probability; the
    remaining ``1 - prime_weight`` is split equally among valid seed nodes.
    If no seeds are present in the graph the prime receives the full weight.
    """
    dist: Dict[int, float] = {}
    valid_seeds = [s for s in seed_ids if s in G]
    seed_share  = (1.0 - prime_weight) / len(valid_seeds) if valid_seeds else 0.0

    dist[prime_id] = prime_weight if valid_seeds else 1.0
    for sid in valid_seeds:
        dist[sid] = dist.get(sid, 0.0) + seed_share
    return dist


def _pagerank_scores(
    G: nx.Graph,
    prime_id: int,
    seed_ids: List[int],
    max_depth: int,
    prime_weight: float,
) -> Dict[int, float]:
    """Run Personalized PageRank and return the score dict.

    ``alpha = 1 - 1 / (max_depth + 1)`` maps the depth intuition onto the
    damping factor (max_depth=5 → alpha ≈ 0.83).
    """
    alpha = 1.0 - 1.0 / (max_depth + 1)
    return nx.pagerank(
        G,
        alpha=alpha,
        personalization=_personalisation(G, prime_id, seed_ids, prime_weight),
        weight="weight",
        max_iter=200,
        tol=1e-6,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def combined_relevance(
    db: GraphDB,
    prime_id: int,
    seed_ids: Iterable[int],
    candidate_id: int,
    max_depth: int = 5,
    prime_weight: float = 0.7,
) -> float:
    """Score how relevant *candidate_id* is given a prime node and seed nodes.

    Runs Personalized PageRank over the full graph and returns the PPR score
    of *candidate_id* — a value in ``(0, 1]`` where higher means more
    relevant.  The score is normalised by the graph size so it is comparable
    across calls on the same graph.

    Parameters:
        db:           Open :class:`~graph_lib.db.GraphDB` instance.
        prime_id:     The primary node of interest.
        seed_ids:     Iterable of contextually related seed node IDs.
        candidate_id: The node being scored.
        max_depth:    Controls the PPR damping factor (default 5 → alpha ≈ 0.83).
        prime_weight: Restart probability assigned to the prime node (default 0.7).

    Returns:
        A float in ``(0, 1]`` — higher means more relevant.
    """
    if not (0.0 <= prime_weight <= 1.0):
        raise ValueError(
            f"prime_weight must be in [0, 1], got {prime_weight!r}"
        )

    G = _build_graph(db)
    if prime_id not in G or candidate_id not in G:
        return 0.0

    scores = _pagerank_scores(G, prime_id, list(seed_ids), max_depth, prime_weight)
    return scores.get(candidate_id, 0.0)


def top_k_nodes(
    db: GraphDB,
    prime_id: int,
    seed_ids: Iterable[int],
    k: int,
    max_depth: int = 5,
    prime_weight: float = 0.7,
    exclude: Optional[Iterable[int]] = None,
) -> List[Tuple[float, int]]:
    """Return the *k* most relevant nodes given a prime node and seed nodes.

    Uses **Personalized PageRank** (PPR) to score every node in the graph.
    The random-walk restart distribution is split between the prime node
    (weighted by *prime_weight*) and the seed nodes (sharing the remaining
    ``1 - prime_weight`` equally), so the prime node has stronger influence
    on the final ranking than any individual seed.

    Edge probabilities stored in the database are used as edge weights, so
    Gemini-scored subjective similarities feed directly into the walk.

    The prime node is unconditionally excluded from the results.  Seed nodes
    are valid candidates and may appear in the top-k output.  Any node IDs
    in *exclude* are also filtered out.

    Parameters:
        db:           Open :class:`~graph_lib.db.GraphDB` instance.
        prime_id:     The primary node of interest.
        seed_ids:     Iterable of contextually related seed node IDs.
        k:            Number of top nodes to return.
        max_depth:    Controls the PageRank damping factor via
                      ``alpha = 1 - 1 / (max_depth + 1)``.  Higher values
                      allow the walk to travel further before restarting
                      (default 5 → alpha ≈ 0.83).
        prime_weight: Fraction of the restart probability assigned to the
                      prime node (default 0.7).  The remainder is split
                      equally among seed nodes.  Must be in ``[0, 1]``.
        exclude:      Additional node IDs to exclude from the results.

    Returns:
        List of up to *k* ``(score, node_id)`` tuples sorted by score
        descending.  May be shorter than *k* if fewer candidates exist.

    Example::

        top = top_k_nodes(db, prime_id=1, seed_ids=[2, 3], k=5)
        # [(0.85, 5), (0.72, 6), (0.61, 7), (0.44, 8), (0.30, 4)]
    """
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k!r}")
    if not (0.0 <= prime_weight <= 1.0):
        raise ValueError(f"prime_weight must be in [0, 1], got {prime_weight!r}")

    seed_list   = list(seed_ids)
    exclude_ids: Set[int] = {prime_id}
    if exclude is not None:
        exclude_ids.update(exclude)

    G = _build_graph(db)
    if prime_id not in G:
        return []

    scores = _pagerank_scores(G, prime_id, seed_list, max_depth, prime_weight)

    ranked = [
        (score, node_id)
        for node_id, score in scores.items()
        if node_id not in exclude_ids
    ]
    ranked.sort(key=lambda t: t[0], reverse=True)
    return ranked[:k]
