from __future__ import annotations

import math
import re
import hashlib
from collections import Counter
from dataclasses import asdict, dataclass

import networkx as nx
import numpy as np

from .models import Paper
from .ranking import TextEmbedder, paper_text


GENERIC_TERMS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "based",
    "by",
    "for",
    "from",
    "in",
    "lens",
    "lenses",
    "of",
    "on",
    "optical",
    "the",
    "to",
    "using",
    "visible",
    "with",
}

QUERY_STOP_TERMS = GENERIC_TERMS


@dataclass(slots=True)
class DiscoveredBranch:
    id: str
    label: str
    query: str
    queries: list[str]
    paper_ids: list[str]
    representative_ids: list[str]
    core_paper_count: int
    frontier_paper_count: int
    year_min: int | None
    year_max: int | None
    semantic_coherence: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def discover_branches(
    papers: dict[str, Paper],
    core_ids: set[str],
    embedder: TextEmbedder,
    vectors_by_id: dict[str, np.ndarray] | None = None,
    semantic_neighbors: int = 8,
    semantic_threshold: float = 0.67,
    resolution: float = 2.0,
    min_branch_size: int = 4,
    query_prefix: str | None = None,
) -> list[DiscoveredBranch]:
    paper_ids = list(papers)
    if vectors_by_id is None:
        vectors = embedder.embed([paper_text(papers[paper_id]) for paper_id in paper_ids])
    else:
        vectors = np.vstack([vectors_by_id[paper_id] for paper_id in paper_ids])
    similarities = vectors @ vectors.T
    graph = nx.Graph()
    graph.add_nodes_from(paper_ids)

    for index, paper_id in enumerate(paper_ids):
        neighbor_indexes = np.argsort(similarities[index])[::-1][1 : semantic_neighbors + 1]
        for neighbor_index in neighbor_indexes:
            similarity = float(similarities[index, neighbor_index])
            if similarity >= semantic_threshold:
                graph.add_edge(
                    paper_id,
                    paper_ids[neighbor_index],
                    weight=similarity,
                    relation="semantic",
                )
    for citing_id, paper in papers.items():
        for cited_id in paper.referenced_works:
            if cited_id in papers:
                if graph.has_edge(cited_id, citing_id):
                    graph[cited_id][citing_id]["weight"] += 1.0
                    graph[cited_id][citing_id]["relation"] = "citation+semantic"
                else:
                    graph.add_edge(
                        cited_id, citing_id, weight=1.0, relation="citation"
                    )

    communities = nx.community.louvain_communities(
        graph, weight="weight", resolution=resolution, seed=42
    )
    communities = [community for community in communities if len(community) >= min_branch_size]
    terms_by_community = _community_terms(communities, papers)
    branches: list[DiscoveredBranch] = []
    query_prefix = query_prefix or infer_query_prefix(papers, core_ids)
    vector_by_id = {paper_id: vectors[index] for index, paper_id in enumerate(paper_ids)}
    for index, community in enumerate(communities, start=1):
        member_ids = sorted(community)
        terms = terms_by_community[index - 1]
        if not terms:
            continue
        representatives = sorted(
            member_ids,
            key=lambda paper_id: (
                paper_id not in core_ids,
                papers[paper_id].cited_by_count,
            ),
            reverse=True,
        )[:5]
        years = [papers[paper_id].year for paper_id in member_ids if papers[paper_id].year]
        coherence = _coherence([vector_by_id[paper_id] for paper_id in member_ids])
        label = " / ".join(terms[:3])
        branch_queries = [f"{query_prefix} {term}".strip() for term in terms[:5]]
        branch_digest = hashlib.sha256(
            "\n".join(member_ids).encode("utf-8")
        ).hexdigest()[:10]
        branches.append(
            DiscoveredBranch(
                id=f"branch-{branch_digest}",
                label=label,
                query=branch_queries[0],
                queries=branch_queries,
                paper_ids=member_ids,
                representative_ids=representatives,
                core_paper_count=len(community & core_ids),
                frontier_paper_count=len(community - core_ids),
                year_min=min(years) if years else None,
                year_max=max(years) if years else None,
                semantic_coherence=round(coherence, 4),
            )
        )
    return sorted(
        branches,
        key=lambda branch: (
            branch.frontier_paper_count,
            branch.semantic_coherence,
        ),
        reverse=True,
    )


def _community_terms(
    communities: list[set[str]], papers: dict[str, Paper]
) -> list[list[str]]:
    counters: list[Counter[str]] = []
    for community in communities:
        counter: Counter[str] = Counter()
        for paper_id in community:
            tokens = _tokens(papers[paper_id].title)
            counter.update(tokens)
            counter.update(
                f"{left} {right}"
                for left, right in zip(tokens, tokens[1:])
                if left not in GENERIC_TERMS and right not in GENERIC_TERMS
            )
        counters.append(counter)

    document_frequency: Counter[str] = Counter()
    for counter in counters:
        document_frequency.update(counter.keys())
    branch_count = max(len(counters), 1)
    output: list[list[str]] = []
    for counter in counters:
        scored = []
        total = max(sum(counter.values()), 1)
        for term, count in counter.items():
            if term in GENERIC_TERMS or len(term) < 3:
                continue
            inverse_frequency = math.log((branch_count + 1) / document_frequency[term])
            phrase_bonus = 1.5 if " " in term else 1.0
            scored.append((count / total * inverse_frequency * phrase_bonus, term))
        selected: list[str] = []
        for _, term in sorted(scored, reverse=True):
            if any(term in existing or existing in term for existing in selected):
                continue
            selected.append(term)
            if len(selected) >= 5:
                break
        output.append(selected)
    return output


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9-]+", value.casefold())


def infer_query_prefix(papers: dict[str, Paper], paper_ids: set[str]) -> str:
    counts: Counter[str] = Counter()
    position_scores: Counter[str] = Counter()
    for paper_id in paper_ids:
        if paper_id not in papers:
            continue
        seen: set[str] = set()
        for position, raw_token in enumerate(_tokens(papers[paper_id].title), start=1):
            # Normalize simple plurals without maintaining a field-specific
            # vocabulary (e.g. ``metalenses`` -> ``metalens``).
            token = raw_token[:-2] if raw_token.endswith("ses") else raw_token
            if token in seen or token in QUERY_STOP_TERMS or len(token) < 4:
                continue
            seen.add(token)
            counts[token] += 1
            position_scores[token] += 1.0 / position
    if not counts:
        return "research"
    return max(counts, key=lambda token: (counts[token], position_scores[token], token))


def _coherence(vectors: list[np.ndarray]) -> float:
    if len(vectors) < 2:
        return 1.0
    matrix = np.vstack(vectors)
    similarities = matrix @ matrix.T
    upper = similarities[np.triu_indices(len(vectors), k=1)]
    return float(np.mean(upper)) if len(upper) else 1.0
