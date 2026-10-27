from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Callable
from typing import Protocol

from .models import CandidateEvidence, Paper, ResearchRouteResult
from .ranking import TextEmbedder, semantic_scores
from .search_planner import HistoryPlanner, HistoryPlannerConfig
from .routing import (
    assign_roles,
    build_influence_graph,
    build_reading_list,
    extract_routes,
    score_candidates,
)


class LiteratureProvider(Protocol):
    def resolve_seed(self, raw_seed: str) -> tuple[Paper, list[Paper]]: ...

    def citing_works(
        self,
        work_id: str,
        limit: int = 25,
        from_year: int | None = None,
        to_year: int | None = None,
    ) -> list[Paper]: ...

    def get_works(self, work_ids: list[str]) -> dict[str, Paper]: ...

    def search_works(
        self, query: str, limit: int = 10, sort: str | None = None
    ) -> list[Paper]: ...


class ResearchRoutePipeline:
    def __init__(
        self,
        provider: LiteratureProvider,
        semantic_embedder: TextEmbedder | None = None,
    ) -> None:
        self.provider = provider
        self.semantic_embedder = semantic_embedder

    def build(
        self,
        raw_seeds: list[str],
        max_nodes: int | None = None,
        neighbors_per_seed: int = 20,
        max_routes: int = 3,
        planner_config: HistoryPlannerConfig | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ResearchRouteResult:
        if not 1 <= len(raw_seeds) <= 3:
            raise ValueError("Provide between 1 and 3 seed papers")
        if max_nodes is not None and max_nodes < len(raw_seeds):
            raise ValueError("max_nodes must be at least the number of seeds")

        config = planner_config or HistoryPlannerConfig(citing_limit=neighbors_per_seed)
        retrieval = HistoryPlanner(self.provider, config).plan_and_execute(
            raw_seeds, progress_callback=progress_callback
        )
        papers = retrieval.papers
        seed_ids = retrieval.seeds
        seed_set = set(seed_ids)
        warnings = list(retrieval.warnings)
        candidates: dict[str, CandidateEvidence] = {}
        for paper_id, paper in papers.items():
            roles = set(retrieval.discovery.get(paper_id, set()))
            roles.discard("seed")
            evidence = CandidateEvidence(
                paper_id=paper_id,
                roles={role.split(":", 1)[0] for role in roles},
                seed_links=set(seed_set if paper_id in seed_set else ()),
            )
            if paper_id in seed_set:
                evidence.roles.add("seed")
            if "foundation" in evidence.roles or "historical_reference" in evidence.roles:
                evidence.roles.add("foundation")
            if "frontier" in evidence.roles:
                evidence.roles.add("frontier")
            candidates[paper_id] = evidence

        # Keep bibliographic coupling evidence separate from the number of
        # seeds linked to a candidate. It is a discovery signal, never a route
        # edge or proof of intellectual inheritance.
        for paper_id, evidence in candidates.items():
            references = set(papers[paper_id].referenced_works)
            evidence.shared_reference_count = sum(
                len(references & set(papers[seed_id].referenced_works))
                for seed_id in seed_set
                if seed_id != paper_id and seed_id in papers
            )

        historical_ids = sorted(
            (
                paper_id
                for paper_id, evidence in candidates.items()
                if evidence.roles & {"historical_search", "historical_reference", "foundation"}
            ),
            key=lambda paper_id: (
                papers[paper_id].year is None,
                papers[paper_id].year or 9999,
                -papers[paper_id].cited_by_count,
                paper_id,
            ),
        )
        for rank, paper_id in enumerate(historical_ids, start=1):
            candidates[paper_id].historical_rank = rank

        # Reconstruct citation evidence from the retained metadata. This keeps
        # route extraction independent from semantic or co-citation relations.
        for citing_id, paper in papers.items():
            for cited_id in paper.referenced_works:
                if cited_id not in papers or cited_id == citing_id:
                    continue
                cited_evidence = candidates[cited_id]
                cited_evidence.citation_edges.add((cited_id, citing_id))
                if citing_id in seed_set:
                    cited_evidence.roles.add("foundation")
                    cited_evidence.seed_links.add(citing_id)
                if cited_id in seed_set:
                    candidates[citing_id].roles.add("frontier")
                    candidates[citing_id].seed_links.add(cited_id)

        requested_max_nodes = max_nodes
        if max_nodes is None:
            max_nodes = self._adaptive_node_budget(papers, candidates, seed_set)

        semantic_by_id: dict[str, float] = {}
        if self.semantic_embedder and len(papers) >= 12:
            try:
                if progress_callback:
                    progress_callback("running local semantic ranking")
                raw_scores, _ = semantic_scores(papers, seed_set, self.semantic_embedder)
                # Cosine output is normally [-1, 1]. Keep it as a bounded
                # discovery signal, never as citation evidence.
                semantic_by_id = {
                    paper_id: max(0.0, min(1.0, (score + 1.0) / 2.0))
                    for paper_id, score in raw_scores.items()
                }
            except Exception as exc:  # optional local model must not block a build
                warnings.append(f"Semantic ranking unavailable: {exc}")

        selected_ids = self._select_node_budget(
            papers, candidates, seed_set, max_nodes, semantic_by_id
        )
        papers = {paper_id: papers[paper_id] for paper_id in selected_ids}
        candidates = {
            paper_id: candidates[paper_id]
            for paper_id in selected_ids
            if paper_id in candidates
        }

        if progress_callback:
            progress_callback("building citation graph")
        graph, edge_records = build_influence_graph(papers)
        assign_roles(papers, graph, candidates, seed_set)
        score_candidates(papers, graph, candidates, seed_set, semantic_by_id or None)
        if progress_callback:
            progress_callback("extracting routes and reading list")
        routes = extract_routes(graph, candidates, seed_set, max_routes=max_routes)
        route_edges = {
            edge
            for route in routes
            for edge in zip(route.paper_ids, route.paper_ids[1:])
        }
        # Edge weight is a display aid only. It combines route support and the
        # endpoint ranking signals; it never changes the citation evidence.
        for edge in edge_records:
            key = (edge["source"], edge["target"])
            source_score = candidates.get(edge["source"])
            target_score = candidates.get(edge["target"])
            endpoint_score = 0.0
            if source_score and target_score:
                endpoint_score = (source_score.route_score + target_score.route_score) / 2
            edge["route_support"] = key in route_edges
            raw_weight = min(
                1.0, 0.55 * endpoint_score + (0.45 if key in route_edges else 0.0)
            )
            # A power curve creates a quiet long tail and gives the strongest
            # evidence visibly more presence without inventing edge classes.
            edge["evidence_weight"] = round(raw_weight, 4)
            edge["display_weight"] = round(raw_weight**2.2, 4)
        reading_list = build_reading_list(
            papers, candidates, seed_set, routes, limit=min(15, max_nodes)
        )

        if not routes:
            warnings.append(
                "No multi-paper confirmed citation route was found in the sampled graph."
            )

        return ResearchRouteResult(
            seeds=seed_ids,
            papers=papers,
            edges=edge_records,
            candidates=candidates,
            routes=routes,
            reading_list=reading_list,
            provenance={
                "generated_at": datetime.now(UTC).isoformat(),
                "provider": "OpenAlex",
                "algorithm_version": "prototype-0.2",
            "max_nodes": max_nodes,
            "requested_max_nodes": requested_max_nodes,
            "semantic_ranking": bool(semantic_by_id),
                "neighbors_per_seed": neighbors_per_seed,
                "retrieval": retrieval.to_dict(),
                "candidate_pool_count": len(retrieval.papers),
                "selected_node_count": len(papers),
                "limitations": [
                    "Citation metadata can be incomplete.",
                    "Routes express confirmed citation paths, not causal influence.",
                    "Bridge scores describe only the sampled graph.",
                    "Abstract text rights require a field-level license review before commercialization.",
                ],
            },
            warnings=warnings,
        )

    @staticmethod
    def _history_query(seed: Paper) -> str:
        topics = [topic.strip() for topic in seed.topics if topic.strip()]
        if topics:
            return f"{' '.join(topics[:2])} review"[:120]
        tokens = [token for token in seed.title.split() if len(token) > 3]
        return f"{' '.join(tokens[:6])} review"[:120] if tokens else ""

    @staticmethod
    def _select_node_budget(
        papers: dict[str, Paper],
        candidates: dict[str, CandidateEvidence],
        seed_ids: set[str],
        max_nodes: int,
        semantic_scores: dict[str, float] | None = None,
    ) -> set[str]:
        selected = set(seed_ids)
        remaining = [paper_id for paper_id in candidates if paper_id not in seed_ids]
        def ranking_key(paper_id: str) -> tuple[object, ...]:
            return (
                len(candidates[paper_id].seed_links),
                candidates[paper_id].shared_seed_count,
                ResearchRoutePipeline._topic_overlap(
                    papers[paper_id],
                    [papers[seed_id] for seed_id in seed_ids],
                ),
                (semantic_scores or {}).get(paper_id, 0.0),
                papers[paper_id].citation_percentile or 0,
                papers[paper_id].fwci or 0,
                papers[paper_id].cited_by_count,
            )

        remaining.sort(key=ranking_key, reverse=True)
        history = [
            paper_id
            for paper_id in remaining
            if candidates[paper_id].roles
            & {"historical_search", "historical_reference"}
        ]
        regular = [paper_id for paper_id in remaining if paper_id not in history]
        history.sort(key=ranking_key, reverse=True)
        regular.sort(key=ranking_key, reverse=True)
        history_budget = min(len(history), max(0, (max_nodes - len(seed_ids)) // 5))
        selected.update(history[:history_budget])
        selected.update(regular[: max(0, max_nodes - len(selected))])
        return selected

    @staticmethod
    def _topic_overlap(paper: Paper, seeds: list[Paper]) -> float:
        candidate_topics = {topic.casefold() for topic in paper.topics}
        if not candidate_topics:
            return 0.0
        best = 0.0
        for seed in seeds:
            seed_topics = {topic.casefold() for topic in seed.topics}
            if seed_topics:
                best = max(
                    best,
                    len(candidate_topics & seed_topics)
                    / min(len(candidate_topics), len(seed_topics)),
                )
        return best

    @staticmethod
    def _adaptive_node_budget(
        papers: dict[str, Paper],
        candidates: dict[str, CandidateEvidence],
        seed_ids: set[str],
    ) -> int:
        """Scale the selected graph with the resolved citation neighborhood."""
        connected_edges = sum(len(evidence.citation_edges) for evidence in candidates.values())
        connected_nodes = sum(
            1
            for paper_id, evidence in candidates.items()
            if paper_id not in seed_ids
            and (evidence.citation_edges or evidence.seed_links)
        )
        # sqrt prevents a single very prolific paper from consuming the whole
        # budget, while still giving genuinely branching fields more room.
        import math

        budget = 24 + int(8 * math.sqrt(max(0, connected_edges)))
        budget += min(36, max(0, connected_nodes - 12) // 2)
        return max(len(seed_ids) + 1, min(150, budget))
