"""
graph_lib.graph_agent
~~~~~~~~~~~~~~~~~~~~~
Unified Gemini-powered interface for graph ingestion and summarisation.

``GraphAgent`` holds all shared configuration as object state — the database
connection, Gemini credentials, and tuning parameters — so that per-call
arguments are limited to the node-specific data that actually changes between
calls (IDs, names, and descriptions).

Usage example::

    from graph_lib.db import GraphDB
    from graph_lib.graph_agent import GraphAgent, NodeInput

    with GraphDB() as db:
        agent = GraphAgent(
            db=db,
            gemini_api_key="AIza...",
        )

        prime = NodeInput(node_id=1, name="Python",
                          description="A programming language")
        seeds = [
            NodeInput(node_id=2, name="NumPy",  description="Array library"),
            NodeInput(node_id=3, name="Pandas", description="DataFrame library"),
        ]

        # Ingest nodes and score edges
        agent.ingest(prime=prime, seeds=seeds)

        # Summarise the prime node with top-k related context
        summary = agent.summarise(prime_id=1, seed_ids=[2, 3])
        print(summary)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from itertools import permutations
from typing import Iterable, List, Optional

import google.generativeai as genai

from .db import GraphDB
from .models import GraphEdge, GraphNode
from .traversal import top_k_nodes


# ---------------------------------------------------------------------------
# Public input type
# ---------------------------------------------------------------------------

@dataclass
class NodeInput:
    """Caller-supplied data for a single node to ingest.

    Attributes:
        node_id:     Unique integer ID.  Existing nodes are upserted.
        name:        Human-readable display name.
        description: Caller's current understanding.  Gemini will refine this
                     before it is stored — preserving correct facts and fixing
                     incorrect assumptions.
    """
    node_id: int
    name: str
    description: str


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

        genai.configure(api_key=gemini_api_key)
        self._model = genai.GenerativeModel(gemini_model)

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
                response = self._model.generate_content(prompt)
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
        prompt = (
            f"Concept: \"{name}\"\n"
            f"Description: {description}\n\n"
            f"Rewrite: keep all key information and details, fix any incorrect "
            f"assumptions, be concise. Output only the revised description."
        )
        return self._call_gemini(prompt)

    def _score_edge(
        self,
        from_name: str,
        from_description: str,
        to_name: str,
        to_description: str,
    ) -> float:
        """Return a Gemini-scored relatedness probability in ``[0, 1]``."""
        prompt = (
            f"Source: \"{from_name}\" — {from_description}\n"
            f"Target: \"{to_name}\" — {to_description}\n\n"
            f"Reply with only a float 0.0-1.0: probability that target is "
            f"related to source."
        )
        retry_prompt = (
            f"Source: \"{from_name}\" — {from_description}\n"
            f"Target: \"{to_name}\" — {to_description}\n\n"
            f"You must reply with ONLY a single float between 0.0 and 1.0. "
            f"No words, no explanation — just the number."
        )

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(
        self,
        prime: NodeInput,
        seeds: List[NodeInput],
    ) -> None:
        """Ingest a prime node and seed nodes into the graph.

        Performs three sequential passes:

        **Pass 1 — Description refinement**
            Each node's description is rewritten by Gemini to preserve accurate
            facts and correct any incorrect assumptions.  The updated description
            is persisted to MongoDB.

        **Pass 2 — Edge initialisation**
            A directed edge with ``probability=0.0`` is created (or reset) for
            every ordered pair of distinct nodes in the ingested set.

        **Pass 3 — Edge scoring**
            Gemini is queried once per edge (starting from the prime, then each
            seed) to assign a relatedness probability in ``[0, 1]``.  Only
            edges whose both endpoints belong to the ingested set are scored.

        Parameters:
            prime: The primary :class:`NodeInput` to ingest.
            seeds: List of contextually related :class:`NodeInput` objects.
        """
        all_inputs: List[NodeInput] = [prime] + list(seeds)
        ingested_ids = {n.node_id for n in all_inputs}

        # Pass 1 — refine descriptions and upsert nodes
        self._log("=== Pass 1: Refining node descriptions ===")
        refined: dict[int, GraphNode] = {}

        for node_input in all_inputs:
            self._log(f"  Refining '{node_input.name}' ...")
            refined_desc = self._refine_description(
                node_input.name, node_input.description
            )
            node      = GraphNode(node_input.node_id, node_input.name, refined_desc)
            persisted = self.db.add_node(node)
            refined[node_input.node_id] = persisted
            self._log(
                f"    → {refined_desc[:80]}{'...' if len(refined_desc) > 80 else ''}"
            )

        # Pass 2 — initialise edges to 0.0
        self._log("=== Pass 2: Initialising edges ===")
        for from_id, to_id in permutations(ingested_ids, 2):
            self.db.add_edge(
                GraphEdge(from_node_id=from_id, to_node_id=to_id, probability=0.0)
            )
            self._log(f"  {from_id} → {to_id} = 0.0")

        # Pass 3 — score edges via Gemini
        self._log("=== Pass 3: Scoring edges ===")
        for source in [prime] + list(seeds):
            from_node = refined[source.node_id]
            for edge in self.db.get_edges_from(source.node_id):
                if edge.to_node_id not in ingested_ids:
                    continue
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

        prompt = (
            f"Prime node: \"{prime_node.name}\"\n"
            f"Description: {prime_node.description}\n\n"
            f"Related context:\n{related_block}\n\n"
            f"Summarise the prime node's purpose, key information, and current "
            f"action. Supplement with relevant context from the related nodes. "
            f"Be brief. Output as bullet points only."
        )

        return self._call_gemini(prompt)
