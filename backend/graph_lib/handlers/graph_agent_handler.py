"""
graph_lib.graph_agent
~~~~~~~~~~~~~~~~~~~~~
Unified Gemini-powered interface for graph ingestion and summarisation.

``GraphAgent`` holds all shared configuration as object state — the database
connection, Gemini credentials, and tuning parameters — so that per-call
arguments are limited to the node-specific data that actually changes between
calls.

Ingestion input format
----------------------
Both ``prime`` and ``seeds`` are plain dicts mapping integer node IDs to
caller-supplied description strings::

    prime = {1: "A general-purpose programming language"}
    seeds = {2: "Numerical array library", 3: "DataFrame library"}

Node names are resolved from the database when the node already exists.
For brand-new nodes (not yet in MongoDB) the name defaults to the string
representation of the ID.  In both cases Gemini will propose a refined
canonical name during Pass 1 before the node is persisted.

Usage example::

    from graph_lib.db import GraphDB
    from graph_lib.graph_agent import GraphAgent

    with GraphDB() as db:
        agent = GraphAgent(db=db, gemini_api_key="AIza...")

        agent.ingest(
            prime={1: "A programming language"},
            seeds={2: "Array library", 3: "DataFrame library"},
        )

        summary = agent.summarise(prime_id=1, seed_ids=[2, 3])
        print(summary)
"""

from __future__ import annotations

import re
import time
from itertools import permutations
from typing import Dict, Iterable, List, Optional

from google import genai
from google.genai import types

from . import prompts

from .graph_db import GraphDB
from .models import GraphEdge, GraphNode
from .traversal import top_k_nodes


# ---------------------------------------------------------------------------
# Gemini call constants
# ---------------------------------------------------------------------------

_RETRY_ATTEMPTS  = 3
_RETRY_DELAY_SEC = 2.0
_EDGE_FALLBACK   = 0.1


# ---------------------------------------------------------------------------
# GraphAgent
# ---------------------------------------------------------------------------

class GraphAgent:
    """Gemini-powered agent for ingesting and querying the knowledge graph.

    All shared configuration is stored as instance state so individual method
    calls only need the data that is unique to each invocation.

    Parameters:
        db:            Open :class:`~graph_lib.db.GraphDB` instance.
        gemini_api_key: Google Generative AI API key.
        gemini_model:  Gemini model identifier (default ``"gemini-1.5-flash"``).
        max_depth:     Maximum DFS hops used by traversal functions (default 5).
        prime_weight:  Weight given to the prime node when scoring relevance
                       (default 0.7).  Must be in ``[0, 1]``.
        k:             Default number of top-related nodes to retrieve
                       (default 5).  Can be overridden per ``summarise`` call.
        verbose:       If ``True``, ``ingest`` prints pass-by-pass progress.
    """

    def __init__(
        self,
        db: GraphDB,
        gemini_api_key: str,
        gemini_model: str  = "gemini-1.5-flash",
        max_depth: int     = 5,
        prime_weight: float = 0.7,
        k: int             = 5,
        verbose: bool      = False,
    ) -> None:
        if not (0.0 <= prime_weight <= 1.0):
            raise ValueError(
                f"prime_weight must be in [0, 1], got {prime_weight!r}"
            )
        if k <= 0:
            raise ValueError(f"k must be a positive integer, got {k!r}")

        self.db           = db
        self.max_depth    = max_depth
        self.prime_weight = prime_weight
        self.k            = k
        self.verbose      = verbose
        self.gemini_model = gemini_model

        self._client = genai.Client(api_key=gemini_api_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def _call_gemini(self, prompt: str) -> str:
        """Send *prompt* to Gemini; retry on transient errors."""
        last_exc: Optional[Exception] = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.gemini_model,
                    contents=prompt
                )
                return response.text.strip()
            except Exception as exc:
                last_exc = exc
                if attempt < _RETRY_ATTEMPTS:
                    time.sleep(_RETRY_DELAY_SEC)
        raise RuntimeError(
            f"Gemini call failed after {_RETRY_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

    def _refine_description(self, name: str, description: str) -> str:
        """Return a Gemini-refined version of *description* for *name*."""
        prompt = prompts.get_refine_description_prompt(name, description)
        return self._call_gemini(prompt)

    def _refine_name(self, name: str, description: str) -> str:
        """Return a Gemini-refined canonical name for a node.

        The refined name should be concise, properly capitalised, and
        unambiguous given the description.  Falls back to the original *name*
        if the response is empty or suspiciously long (> 80 chars).
        """
        prompt = prompts.get_refine_name_prompt(name, description)
        refined = self._call_gemini(prompt).strip().strip('"').strip("'")
        if not refined or len(refined) > 80:
            return name
        return refined

    def _discover_missing_links(
        self,
        node: GraphNode,
        existing_neighbour_names: List[str],
    ) -> Optional[tuple[str, str]]:
        """Ask Gemini whether *node* has key related topics not yet in the graph.

        Returns a ``(name, description)`` tuple for one missing topic if Gemini
        identifies a gap, or ``None`` if no important link is missing.

        The caller is responsible for assigning an ID and persisting the result.

        Parameters:
            node:                     The node being examined.
            existing_neighbour_names: Names of nodes already linked to *node*
                                      in the database, so Gemini knows what is
                                      already covered.
        """
        neighbours_str = (
            ", ".join(f'"{n}"' for n in existing_neighbour_names)
            if existing_neighbour_names
            else "none"
        )
        prompt = prompts.get_discover_missing_links_prompt(node.name, node.description, neighbours_str)
        raw = self._call_gemini(prompt).strip()

        if raw.upper() == "NONE" or raw.upper().startswith("NONE"):
            return None

        name_match = re.search(r"(?i)^NAME:\s*(.+)$", raw, re.MULTILINE)
        desc_match = re.search(r"(?i)^DESCRIPTION:\s*(.+)$", raw, re.MULTILINE)

        if not name_match or not desc_match:
            # Response didn't match the expected format — treat as no gap found
            self._log(f"    (could not parse missing-link response: {raw[:60]!r})")
            return None

        return name_match.group(1).strip(), desc_match.group(1).strip()

    def _score_edge(
        self,
        from_name: str,
        from_description: str,
        to_name: str,
        to_description: str,
    ) -> float:
        """Return a Gemini-scored relatedness probability in ``[0, 1]``."""
        prompt = prompts.get_score_edge_prompt(from_name, from_description, to_name, to_description)
        retry_prompt = prompts.get_score_edge_retry_prompt(from_name, from_description, to_name, to_description)

        for p in (prompt, retry_prompt):
            raw   = self._call_gemini(p)
            match = re.search(r"[0-9]*\.?[0-9]+", raw)
            if not match:
                continue
            try:
                value = float(match.group())
                if 0.0 <= value <= 1.0:
                    return value
            except ValueError:
                continue

        return _EDGE_FALLBACK

    def _next_node_id(self) -> int:
        """Return one more than the highest node_id currently in the database."""
        all_nodes = self.db.get_all_nodes()
        return max((n.node_id for n in all_nodes), default=0) + 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(
        self,
        prime: Dict[int, str],
        seeds: Dict[int, str],
    ) -> None:
        """Ingest a prime node and seed nodes into the graph.

        Performs four sequential passes:

        **Pass 1 — Name and description refinement**
            Gemini proposes a canonical name for each node, then rewrites its
            description to preserve accurate facts and correct any incorrect
            assumptions.  Both are persisted to MongoDB.

        **Pass 1b — Missing-link discovery**
            For each ingested node Gemini is asked whether any important related
            topic is absent from the graph.  If a gap is identified, a new node
            is created and edges between it and the originating node are
            initialised and scored immediately.

        **Pass 2 — Edge initialisation**
            A directed edge with ``probability=0.0`` is created (or reset) for
            every ordered pair of distinct nodes in the ingested set (including
            any nodes added in Pass 1b).

        **Pass 3 — Edge scoring**
            Gemini is queried once per edge (starting from the prime, then each
            seed) to assign a relatedness probability in ``[0, 1]``.  Only
            edges whose both endpoints belong to the ingested set are scored.

        Parameters:
            prime: ``{node_id: description}`` — exactly one entry for the
                   primary node.
            seeds: ``{node_id: description}`` — one entry per seed node.

        Raises:
            ValueError: If *prime* does not contain exactly one entry.
        """
        if len(prime) != 1:
            raise ValueError(
                f"prime must contain exactly one {{id: description}} entry, "
                f"got {len(prime)}."
            )

        # Merge into an ordered list: prime first, then seeds.
        all_items: List[tuple[int, str]] = (
            list(prime.items()) + list(seeds.items())
        )
        ingested_ids: set[int] = {node_id for node_id, _ in all_items}

        def _resolve_name(node_id: int) -> str:
            existing = self.db.get_node(node_id)
            return existing.name if existing else str(node_id)

        # ------------------------------------------------------------------
        # Pass 1 — refine names and descriptions, then upsert nodes
        # ------------------------------------------------------------------
        self._log("=== Pass 1: Refining node names and descriptions ===")
        refined: Dict[int, GraphNode] = {}

        for node_id, description in all_items:
            name = _resolve_name(node_id)
            self._log(f"  Refining '{name}' ...")
            refined_name = self._refine_name(name, description)
            if refined_name != name:
                self._log(f"    name: '{name}' → '{refined_name}'")
                name = refined_name
            refined_desc = self._refine_description(name, description)
            node      = GraphNode(node_id, name, refined_desc)
            persisted = self.db.add_node(node)
            refined[node_id] = persisted
            self._log(
                f"    → {refined_desc[:80]}{'...' if len(refined_desc) > 80 else ''}"
            )

        # ------------------------------------------------------------------
        # Pass 1b — discover and add missing linked topics
        # ------------------------------------------------------------------
        self._log("=== Pass 1b: Discovering missing links ===")

        # Iterate over a snapshot — refined may grow as we discover new nodes.
        for node_id in list(refined):
            node = refined[node_id]

            # Collect names of nodes already linked to this one in the DB.
            linked_names: List[str] = []
            for edge in self.db.get_edges_from(node.node_id):
                neighbour = self.db.get_node(edge.to_node_id)
                if neighbour:
                    linked_names.append(neighbour.name)

            self._log(f"  Checking '{node.name}' for missing links ...")
            result = self._discover_missing_links(node, linked_names)

            if result is None:
                self._log("    → no gap identified")
                continue

            new_name, new_desc = result
            new_id = self._next_node_id()
            self._log(f"    → adding new node #{new_id} '{new_name}'")

            new_node = GraphNode(new_id, new_name, new_desc)
            persisted_new = self.db.add_node(new_node)
            refined[new_id] = persisted_new
            ingested_ids.add(new_id)

            # Initialise bidirectional edges between the originating node and
            # the new node, then score them immediately.
            for from_id, to_id in [(node.node_id, new_id), (new_id, node.node_id)]:
                self.db.add_edge(
                    GraphEdge(from_node_id=from_id, to_node_id=to_id, probability=0.0)
                )
                from_n = refined[from_id]
                to_n   = refined[to_id]
                prob   = self._score_edge(
                    from_n.name, from_n.description,
                    to_n.name,   to_n.description,
                )
                self.db.add_edge(GraphEdge(from_id, to_id, prob))
                self._log(f"    scored {from_id} → {to_id}: {prob:.4f}")

        # ------------------------------------------------------------------
        # Pass 2 — initialise all remaining edges to 0.0
        # ------------------------------------------------------------------
        self._log("=== Pass 2: Initialising edges ===")
        for from_id, to_id in permutations(ingested_ids, 2):
            # Skip pairs already scored in Pass 1b
            existing = self.db.get_edge(from_id, to_id)
            if existing and existing.probability > 0.0:
                continue
            self.db.add_edge(
                GraphEdge(from_node_id=from_id, to_node_id=to_id, probability=0.0)
            )
            self._log(f"  {from_id} → {to_id} = 0.0")

        # ------------------------------------------------------------------
        # Pass 3 — score remaining edges via Gemini
        # ------------------------------------------------------------------
        self._log("=== Pass 3: Scoring edges ===")
        for node_id in list(refined):
            from_node = refined[node_id]
            for edge in self.db.get_edges_from(node_id):
                if edge.to_node_id not in ingested_ids:
                    continue
                if edge.probability > 0.0:
                    continue  # already scored in Pass 1b
                to_node = refined[edge.to_node_id]
                self._log(f"  Scoring '{from_node.name}' → '{to_node.name}' ...")
                prob = self._score_edge(
                    from_node.name, from_node.description,
                    to_node.name,   to_node.description,
                )
                self.db.add_edge(
                    GraphEdge(from_node.node_id, to_node.node_id, prob)
                )
                self._log(f"    → {prob:.4f}")

        self._log("=== Ingestion complete ===")

    def summarise(
        self,
        prime_id: int,
        seed_ids: Iterable[int],
        k: Optional[int] = None,
    ) -> str:
        """Summarise a prime node with top-k related context via Gemini.

        Fetches the prime node's description, retrieves the *k* most relevant
        nodes under the prime + seed context, then asks Gemini for a concise
        bullet-point summary covering purpose, key information, and current
        action.

        Parameters:
            prime_id:  Integer ID of the node to summarise.
            seed_ids:  Iterable of contextually related seed node IDs.
            k:         Override the instance default ``self.k`` for this call.

        Returns:
            Gemini's bullet-point summary as a plain string.

        Raises:
            ValueError:   If the prime node is not found in the database.
            RuntimeError: If all Gemini retry attempts fail.
        """
        effective_k = k if k is not None else self.k

        prime_node = self.db.get_node(prime_id)
        if prime_node is None:
            raise ValueError(f"Prime node id={prime_id} not found in database.")

        seed_list    = list(seed_ids)
        topk_results = top_k_nodes(
            db=self.db,
            prime_id=prime_id,
            seed_ids=seed_list,
            k=effective_k,
            max_depth=self.max_depth,
            prime_weight=self.prime_weight,
        )

        related_lines: List[str] = []
        for score, node_id in topk_results:
            node = self.db.get_node(node_id)
            if node is None:
                continue
            related_lines.append(
                f"- {node.name} (relevance {score:.2f}): {node.description}"
            )

        related_block = (
            "\n".join(related_lines) if related_lines else "None available."
        )

        prompt = prompts.get_summarise_prompt(prime_node.name, prime_node.description, related_block)

        return self._call_gemini(prompt)
