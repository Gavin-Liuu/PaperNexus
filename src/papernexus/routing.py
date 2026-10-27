from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

import networkx as nx

from .models import CandidateEvidence, Paper, ReadingItem, Route


ROLE_PRIORITY = {
    "seed": 5,
    "turning_point": 4,
    "foundation": 3,
    "frontier": 2,
    "branch": 1,
}


def build_influence_graph(
    papers: dict[str, Paper],
) -> tuple[nx.DiGraph, list[dict[str, Any]]]:
    """Build a display DAG with confirmed citation edges oriented earlier -> later."""
    graph = nx.DiGraph()
    graph.add_nodes_from(papers)
    edge_records: list[dict[str, Any]] = []
    for citing_id, paper in papers.items():
        for cited_id in paper.referenced_works:
            if cited_id not in papers or cited_id == citing_id:
                continue
            cited_paper = papers[cited_id]
            if (
                cited_paper.year is not None
                and paper.year is not None
                and cited_paper.year > paper.year
            ):
                continue
            graph.add_edge(cited_id, citing_id, relation="citation")
            edge_records.append(
                {
                    "source": cited_id,
                    "target": citing_id,
                    "type": "citation",
                    "evidence_status": "confirmed_metadata",
                    "raw_direction": f"{citing_id}->{cited_id}",
                }
            )
    return graph, edge_records


def score_candidates(
    papers: dict[str, Paper],
    graph: nx.DiGraph,
    candidates: dict[str, CandidateEvidence],
    seed_ids: set[str],
    semantic_scores: dict[str, float] | None = None,
) -> None:
    if graph.number_of_edges():
        raw_betweenness = nx.betweenness_centrality(graph, normalized=True)
    else:
        raw_betweenness = {paper_id: 0.0 for paper_id in papers}

    for paper_id, evidence in candidates.items():
        paper = papers[paper_id]
        evidence.shared_seed_count = len(evidence.seed_links)
        seed_coverage = min(
            1.0, evidence.shared_seed_count / max(len(seed_ids), 1)
        )
        topic_affinity = _topic_affinity(
            paper,
            [papers[seed_id] for seed_id in evidence.seed_links if seed_id in papers],
        )
        # A direct citation is useful discovery evidence, but it is not by
        # itself proof that a highly cited generic background paper belongs to
        # the seed's method. Topic/title affinity therefore carries most of
        # the overview visibility weight.
        if paper_id in seed_ids:
            evidence.relevance_score = 1.0
        else:
            metadata_relevance = 0.2 * seed_coverage + 0.8 * topic_affinity
            evidence.semantic_score = max(
                0.0, min(1.0, (semantic_scores or {}).get(paper_id, 0.0))
            )
            evidence.relevance_score = (
                0.55 * metadata_relevance + 0.45 * evidence.semantic_score
                if semantic_scores
                else metadata_relevance
            )
        percentile = paper.citation_percentile
        if percentile is not None:
            evidence.influence_score = max(0.0, min(1.0, percentile))
        elif paper.fwci is not None:
            evidence.influence_score = min(1.0, math.log1p(max(paper.fwci, 0.0)) / math.log(11))
        else:
            evidence.influence_score = min(
                1.0, math.log1p(max(paper.cited_by_count, 0)) / math.log(10001)
            )
        evidence.bridge_score = raw_betweenness.get(paper_id, 0.0)
        direct_seed_bonus = 1.0 if evidence.seed_links else 0.0
        evidence.route_score = (
            0.45 * evidence.relevance_score
            + 0.25 * evidence.influence_score
            + 0.20 * evidence.bridge_score
            + 0.10 * direct_seed_bonus
        )
        evidence.selection_reasons = describe_selection(evidence, paper_id in seed_ids)


def _topic_affinity(paper: Paper, seeds: list[Paper]) -> float:
    candidate_topics = {topic.casefold() for topic in paper.topics}
    topic_score = max(
        (
            len(candidate_topics & seed_topics)
            / min(len(candidate_topics), len(seed_topics))
            for seed in seeds
            if (seed_topics := {topic.casefold() for topic in seed.topics})
        ),
        default=0.0,
    )
    if topic_score:
        return topic_score
    # OpenAlex topic assignment is sparse for older papers. A small lexical
    # fallback keeps obviously unrelated, high-citation references subdued.
    stopwords = {
        "the", "and", "for", "with", "from", "using", "based", "into",
        "this", "that", "a", "an", "of", "to", "in", "on", "by",
    }
    candidate_words = {
        token.casefold().strip(".,:;()[]{}")
        for token in paper.title.split()
        if len(token) > 3 and token.casefold() not in stopwords
    }
    return max(
        (
            len(candidate_words & {
                token.casefold().strip(".,:;()[]{}")
                for token in seed.title.split()
                if len(token) > 3 and token.casefold() not in stopwords
            })
            / max(1, min(len(candidate_words), len(seed.title.split())))
            for seed in seeds
        ),
        default=0.0,
    )


def describe_selection(evidence: CandidateEvidence, is_seed: bool) -> list[str]:
    if is_seed:
        return ["User-provided seed paper"]
    reasons: list[str] = []
    if "foundation" in evidence.roles:
        reasons.append(
            f"Cited by {max(evidence.shared_seed_count, 1)} seed or route paper(s)"
        )
    if "frontier" in evidence.roles:
        reasons.append(
            f"Cites {max(evidence.shared_seed_count, 1)} seed or route paper(s)"
        )
    if evidence.bridge_score > 0:
        reasons.append("Bridges paths in the current sampled graph")
    if evidence.influence_score >= 0.9:
        reasons.append("High field/year-normalized or fallback citation influence")
    return reasons or ["Directly connected to a seed paper"]


def assign_roles(
    papers: dict[str, Paper],
    graph: nx.DiGraph,
    candidates: dict[str, CandidateEvidence],
    seed_ids: set[str],
) -> None:
    seed_years = [papers[seed_id].year for seed_id in seed_ids if papers[seed_id].year]
    seed_year = round(sum(seed_years) / len(seed_years)) if seed_years else None
    for paper_id, evidence in candidates.items():
        if paper_id in seed_ids:
            evidence.roles.add("seed")
            continue
        paper_year = papers[paper_id].year
        if seed_year is not None and paper_year is not None:
            if paper_year < seed_year:
                evidence.roles.add("foundation")
            elif paper_year > seed_year:
                evidence.roles.add("frontier")
        if graph.in_degree(paper_id) and graph.out_degree(paper_id):
            evidence.roles.add("turning_point")
        if not evidence.roles:
            evidence.roles.add("branch")


def extract_routes(
    graph: nx.DiGraph,
    candidates: dict[str, CandidateEvidence],
    seed_ids: set[str],
    max_routes: int = 3,
    max_route_length: int = 10,
) -> list[Route]:
    ranked_paths: dict[tuple[str, ...], float] = {}
    for seed_id in sorted(seed_ids):
        ancestors = nx.ancestors(graph, seed_id)
        descendants = nx.descendants(graph, seed_id)
        foundations = sorted(
            ancestors,
            key=lambda node: candidates[node].route_score,
            reverse=True,
        )[:5]
        frontiers = sorted(
            descendants,
            key=lambda node: candidates[node].route_score,
            reverse=True,
        )[:5]

        left_paths: list[list[str]] = [[seed_id]]
        for foundation in foundations:
            try:
                left_paths.append(nx.shortest_path(graph, foundation, seed_id))
            except nx.NetworkXNoPath:
                pass
        right_paths: list[list[str]] = [[seed_id]]
        for frontier in frontiers:
            try:
                right_paths.append(nx.shortest_path(graph, seed_id, frontier))
            except nx.NetworkXNoPath:
                pass

        for left in left_paths:
            for right in right_paths:
                combined = left[:-1] + right
                if len(combined) < 2 or len(combined) > max_route_length:
                    continue
                path_key = tuple(combined)
                score = sum(candidates[node].route_score for node in combined) / len(combined)
                score += 0.05 * min(len(combined), 6)
                if len(left) > 1 and len(right) > 1:
                    score += 0.15
                ranked_paths[path_key] = max(ranked_paths.get(path_key, 0.0), score)

    selected: list[Route] = []
    used_edges: set[tuple[str, str]] = set()
    for index, (path, score) in enumerate(
        sorted(ranked_paths.items(), key=lambda item: item[1], reverse=True), start=1
    ):
        edges = set(zip(path, path[1:]))
        if selected and edges and len(edges & used_edges) / len(edges) > 0.7:
            continue
        selected.append(
            Route(
                id=f"route-{index}",
                paper_ids=list(path),
                score=round(score, 4),
                evidence_status="confirmed_citation_path",
                explanation=(
                    "A time-consistent path composed only of citation edges present in "
                    "the sampled graph. Importance scores are local ranking aids."
                ),
            )
        )
        used_edges.update(edges)
        if len(selected) >= max_routes:
            break
    return selected


def build_reading_list(
    papers: dict[str, Paper],
    candidates: dict[str, CandidateEvidence],
    seed_ids: set[str],
    routes: Iterable[Route],
    limit: int = 15,
) -> list[ReadingItem]:
    route_nodes = {paper_id for route in routes for paper_id in route.paper_ids}
    ordered = sorted(
        candidates,
        key=lambda paper_id: (
            paper_id in seed_ids,
            paper_id in route_nodes and "turning_point" in candidates[paper_id].roles,
            max(
                (ROLE_PRIORITY.get(role, 0) for role in candidates[paper_id].roles),
                default=0,
            ),
            candidates[paper_id].route_score,
        ),
        reverse=True,
    )
    counts = defaultdict(int)
    items: list[ReadingItem] = []
    tier_limits = {"read_first": 5, "background": 4, "frontier": 4, "optional_branch": 5}
    for paper_id in ordered:
        evidence = candidates[paper_id]
        roles = evidence.roles
        if paper_id in seed_ids or (
            paper_id in route_nodes and "turning_point" in roles
        ):
            tier = "read_first"
        elif "foundation" in roles:
            tier = "background"
        elif "frontier" in roles:
            tier = "frontier"
        else:
            tier = "optional_branch"
        if counts[tier] >= tier_limits[tier]:
            continue
        counts[tier] += 1
        items.append(
            ReadingItem(
                paper_id=paper_id,
                tier=tier,
                reason="; ".join(evidence.selection_reasons),
                connected_to=sorted(evidence.seed_links),
                evidence_status=(
                    "user_provided_seed"
                    if paper_id in seed_ids
                    else (
                        "confirmed_citation_metadata"
                        if evidence.citation_edges
                        else "ranking_only"
                    )
                ),
            )
        )
        if len(items) >= limit:
            break
    return items
