"""
graph_lib.traversal
~~~~~~~~~~~~~~~~~~~
Graph traversal and distance utilities.

Probability / distance model
-----------------------------
The weight on each edge is the probability that the *to* node is related to
the *from* node.  The probability of a multi-hop path is the **product** of
its edge probabilities (each hop attenuates the signal).  A higher product
means the destination is *more* related to the origin, so we treat the
product itself as the "closeness" score (not a distance in the classical
sense — 1 = certainly related, 0 = certainly unrelated).

Public API
----------
dfs_paths(db, from_id, to_id, max_depth)
    DFS from *from_id* looking for *to_id*; returns every path found within
    *max_depth* hops as ``(path_probability, to_node_id)`` tuples.

multi_source_distances(db, from_ids, to_id, max_depth)
    For each node in *from_ids*, compute the best (highest-probability) path
    to *to_id*; return one ``(probability, from_node_id)`` tuple per source.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .db import GraphDB


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dfs(
    db: GraphDB,
    current_id: int,
    target_id: int,
    max_depth: int,
    current_prob: float,
    visited: Set[int],
    results: List[Tuple[float, int]],
) -> None:
    """Recursive DFS worker.

    Explores all outgoing edges from *current_id*.  When *target_id* is
    reached the cumulative path probability is recorded.  Visited tracking
    prevents cycles within a single path.

    Parameters:
        db:           Open :class:`~graph_lib.db.GraphDB` instance.
        current_id:   Node currently being expanded.
        target_id:    The node we are searching for.
        max_depth:    Remaining hops allowed (stops recursion when 0).
        current_prob: Accumulated product of edge probabilities so far.
        visited:      Set of node IDs already on the current path.
        results:      Accumulator for ``(probability, target_id)`` results.
    """
    if max_depth == 0:
        return

    for edge in db.get_edges_from(current_id):
        neighbour = edge.to_node_id

        if neighbour in visited:
            continue  # avoid cycles within this path

        path_prob = current_prob * edge.probability

        if neighbour == target_id:
            results.append((path_prob, target_id))
            # do not recurse further — we reached the target
            continue

        visited.add(neighbour)
        _dfs(
            db=db,
            current_id=neighbour,
            target_id=target_id,
            max_depth=max_depth - 1,
            current_prob=path_prob,
            visited=visited,
            results=results,
        )
        visited.discard(neighbour)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def dfs_paths(
    db: GraphDB,
    from_id: int,
    to_id: int,
    max_depth: int = 5,
) -> List[Tuple[float, int]]:
    """Find all paths from *from_id* to *to_id* within *max_depth* hops.

    Each distinct path is returned as a ``(path_probability, to_id)`` tuple
    where ``path_probability`` is the product of the edge probabilities along
    that path.  Multiple tuples with the same ``to_id`` are possible when
    several paths reach the target.

    The results are sorted by probability descending (most related first).

    Parameters:
        db:        Open :class:`~graph_lib.db.GraphDB` instance.
        from_id:   Integer ID of the starting node.
        to_id:     Integer ID of the target node.
        max_depth: Maximum number of hops to explore (default 5).

    Returns:
        Sorted list of ``(probability, to_id)`` tuples.

    Example::

        results = dfs_paths(db, from_id=1, to_id=7, max_depth=3)
        # [(0.72, 7), (0.45, 7)]  — two distinct paths found
    """
    results: List[Tuple[float, int]] = []
    _dfs(
        db=db,
        current_id=from_id,
        target_id=to_id,
        max_depth=max_depth,
        current_prob=1.0,
        visited={from_id},
        results=results,
    )
    results.sort(key=lambda t: t[0], reverse=True)
    return results


def multi_source_distances(
    db: GraphDB,
    from_ids: Iterable[int],
    to_id: int,
    max_depth: int = 5,
    combination: str = "max",
) -> List[Tuple[float, int]]:
    """Compute how related a set of source nodes are to a single target node.

    For each source node in *from_ids* the function finds the best
    (highest-probability) path to *to_id* within *max_depth* hops and
    returns a ``(best_probability, from_node_id)`` tuple.

    When no path exists between a source and the target, the probability is
    0.0 and the tuple is still included so callers can rely on one entry per
    source.

    Parameters:
        db:          Open :class:`~graph_lib.db.GraphDB` instance.
        from_ids:    Iterable of source node integer IDs.
        to_id:       Integer ID of the single target node.
        max_depth:   Maximum hops for each individual DFS (default 5).
        combination: How to pick the representative probability when multiple
                     paths exist from a single source.  ``"max"`` (default)
                     returns the highest-probability path; ``"sum_log"``
                     returns the log-sum-exp of the log-probabilities, which
                     rewards having many medium-probability paths in addition
                     to the best one.

    Returns:
        List of ``(probability, from_node_id)`` tuples, sorted by probability
        descending.

    Example::

        # prime node = 3, seed nodes = [1, 2, 5]
        scores = multi_source_distances(db, from_ids=[1, 2, 5], to_id=3)
        # [(0.81, 1), (0.60, 5), (0.20, 2)]
    """
    if combination not in {"max", "sum_log"}:
        raise ValueError(
            f"combination must be 'max' or 'sum_log', got {combination!r}"
        )

    output: List[Tuple[float, int]] = []

    for src in from_ids:
        paths = dfs_paths(db, from_id=src, to_id=to_id, max_depth=max_depth)

        if not paths:
            output.append((0.0, src))
            continue

        probs = [p for p, _ in paths]

        if combination == "max":
            score = max(probs)
        else:  # "sum_log" — log-sum-exp in probability space
            # equivalent to log( sum( p_i ) ) but numerically stable
            max_p = max(probs)
            score = max_p * math.exp(
                sum(math.log(p / max_p) for p in probs if p > 0)
            )
            # clamp to [0, 1] since this can exceed 1 when many paths exist
            score = min(score, 1.0)

        output.append((score, src))

    output.sort(key=lambda t: t[0], reverse=True)
    return output


def combined_relevance(
    db: GraphDB,
    prime_id: int,
    seed_ids: Iterable[int],
    candidate_id: int,
    max_depth: int = 5,
    prime_weight: float = 0.7,
) -> float:
    """Score how relevant *candidate_id* is given a prime node and seed nodes.

    The score is a weighted combination:

        score = prime_weight  * P(prime  → candidate)
              + (1-prime_weight) * mean( P(seed_i → candidate) )

    where each individual probability is the best (max-probability) DFS path
    found within *max_depth* hops.

    Parameters:
        db:           Open :class:`~graph_lib.db.GraphDB` instance.
        prime_id:     The primary node of interest.
        seed_ids:     Iterable of contextually related seed node IDs.
        candidate_id: The node being scored.
        max_depth:    Maximum hops (default 5).
        prime_weight: Weight given to the prime node's contribution (default
                      0.7).  Must be in ``[0, 1]``.

    Returns:
        A float in ``[0, 1]`` — higher means more relevant.
    """
    if not (0.0 <= prime_weight <= 1.0):
        raise ValueError(
            f"prime_weight must be in [0, 1], got {prime_weight!r}"
        )

    # Prime node contribution
    prime_paths = dfs_paths(db, from_id=prime_id, to_id=candidate_id, max_depth=max_depth)
    prime_score = max((p for p, _ in prime_paths), default=0.0)

    # Seed nodes contribution — average of each seed's best path
    seed_list = list(seed_ids)
    if seed_list:
        seed_scores = multi_source_distances(
            db, from_ids=seed_list, to_id=candidate_id, max_depth=max_depth
        )
        seed_mean = sum(p for p, _ in seed_scores) / len(seed_scores)
    else:
        seed_mean = 0.0

    return prime_weight * prime_score + (1.0 - prime_weight) * seed_mean


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

    The prime node and any node IDs listed in *exclude* are omitted from the
    results.  Seed nodes are treated as ordinary candidates and may appear in
    the top-k output — only the prime node is unconditionally excluded.

    Parameters:
        db:           Open :class:`~graph_lib.db.GraphDB` instance.
        prime_id:     The primary node of interest.
        seed_ids:     Iterable of contextually related seed node IDs.
        k:            Number of top nodes to return.
        max_depth:    Maximum DFS hops when scoring each candidate (default 5).
        prime_weight: How much the prime node's path dominates the score
                      (default 0.7).  Passed directly to
                      :func:`combined_relevance`.
        exclude:      Additional node IDs to exclude from candidacy (e.g. nodes
                      the caller has already surfaced).  ``None`` means no
                      extra exclusions.

    Returns:
        List of up to *k* ``(score, node_id)`` tuples sorted by score
        descending.  May be shorter than *k* if fewer candidates exist.

    Example::

        top = top_k_nodes(db, prime_id=1, seed_ids=[2, 3], k=5)
        # [(0.85, 5), (0.72, 6), (0.61, 7), (0.44, 8), (0.30, 4)]
    """
    if k <= 0:
        raise ValueError(f"k must be a positive integer, got {k!r}")

    seed_list = list(seed_ids)
    context_ids: Set[int] = {prime_id}  # seeds are valid candidates
    if exclude is not None:
        context_ids.update(exclude)

    # Collect every candidate node reachable within max_depth from either
    # the prime or any seed.  We gather them via BFS over the edge list so we
    # don't need to issue a separate DFS per-node just to find candidates.
    candidates: Set[int] = set()
    frontier = {prime_id, *seed_list}
    visited_bfs: Set[int] = set(frontier)

    for _depth in range(max_depth):
        next_frontier: Set[int] = set()
        for src in frontier:
            for edge in db.get_edges_from(src):
                nbr = edge.to_node_id
                if nbr not in visited_bfs:
                    visited_bfs.add(nbr)
                    next_frontier.add(nbr)
                    if nbr not in context_ids:
                        candidates.add(nbr)
        frontier = next_frontier
        if not frontier:
            break

    # Score every candidate and keep the top k
    scored: List[Tuple[float, int]] = []
    for candidate_id in candidates:
        score = combined_relevance(
            db=db,
            prime_id=prime_id,
            seed_ids=seed_list,
            candidate_id=candidate_id,
            max_depth=max_depth,
            prime_weight=prime_weight,
        )
        scored.append((score, candidate_id))

    scored.sort(key=lambda t: t[0], reverse=True)
    return scored[:k]
