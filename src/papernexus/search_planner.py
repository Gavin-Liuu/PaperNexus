from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .models import Paper


class PlannerProvider(Protocol):
    def resolve_seed(self, raw_seed: str) -> tuple[Paper, list[Paper]]: ...

    def get_works(self, work_ids: list[str]) -> dict[str, Paper]: ...

    def citing_works(
        self,
        work_id: str,
        limit: int = 25,
        from_year: int | None = None,
        to_year: int | None = None,
    ) -> list[Paper]: ...

    def search_works(
        self, query: str, limit: int = 10, sort: str | None = None
    ) -> list[Paper]: ...


@dataclass(slots=True)
class HistoryPlannerConfig:
    max_text_queries: int = 6
    max_http_attempts: int = 30
    max_backward_rounds: int = 2
    max_candidate_pool: int = 500
    max_display_nodes: int = 150
    search_limit: int = 25
    citing_limit: int = 20
    anchor_limit: int = 8
    backfill_limit_per_round: int = 120
    max_seconds: float = 600.0
    enable_semantic_search: bool = False


@dataclass(slots=True)
class RetrievalAction:
    kind: str
    anchor_id: str | None = None
    query: str | None = None
    direction: str | None = None
    depth: int = 0
    estimated_requests: int = 1
    reason: str = ""
    result_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalResult:
    seeds: list[str]
    papers: dict[str, Paper]
    discovery: dict[str, set[str]]
    actions: list[RetrievalAction]
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seeds": self.seeds,
            "papers": {paper_id: paper.to_dict() for paper_id, paper in self.papers.items()},
            "discovery": {
                paper_id: sorted(values) for paper_id, values in self.discovery.items()
            },
            "actions": [action.to_dict() for action in self.actions],
            "warnings": self.warnings,
            "stats": self.stats,
        }


class HistoryPlanner:
    """Bounded, field-independent retrieval planner.

    It treats text search as an entry point and citation relationships as the
    historical expansion mechanism. The planner never claims that a semantic
    or co-citation relationship is a causal influence edge.
    """

    def __init__(
        self,
        provider: PlannerProvider,
        config: HistoryPlannerConfig | None = None,
    ) -> None:
        self.provider = provider
        self.config = config or HistoryPlannerConfig()

    def plan_and_execute(
        self,
        raw_seeds: list[str],
        progress_callback: Callable[[str], None] | None = None,
    ) -> RetrievalResult:
        if not 1 <= len(raw_seeds) <= 3:
            raise ValueError("Provide between 1 and 3 seed papers")

        papers: dict[str, Paper] = {}
        discovery: defaultdict[str, set[str]] = defaultdict(set)
        actions: list[RetrievalAction] = []
        warnings: list[str] = []
        seeds: list[str] = []
        request_attempts = 0
        resolved_count = 0
        identity_conflicts = 0
        started_at = time.monotonic()
        target_pool = min(self.config.max_candidate_pool, self.config.max_display_nodes)

        def progress(stage: str) -> None:
            if progress_callback:
                progress_callback(stage)

        def check_deadline() -> None:
            if time.monotonic() - started_at > self.config.max_seconds:
                raise TimeoutError(
                    f"Retrieval exceeded the {self.config.max_seconds:.0f}-second budget"
                )

        def add_paper(paper: Paper, source: str, anchor: str | None = None) -> None:
            existing = papers.get(paper.id)
            if existing is None or (not existing.abstract and paper.abstract):
                papers[paper.id] = paper
            discovery[paper.id].add(source)
            if anchor:
                discovery[paper.id].add(f"anchor:{anchor}")

        progress("resolving seeds")
        for raw_seed in raw_seeds:
            check_deadline()
            if request_attempts >= self.config.max_http_attempts:
                warnings.append("Request budget exhausted during seed resolution")
                break
            paper, alternatives = self.provider.resolve_seed(raw_seed)
            request_attempts += 1
            resolved_count += 1
            if paper.id in seeds:
                continue
            seeds.append(paper.id)
            add_paper(paper, "seed")
            if len(alternatives) > 1:
                identity_conflicts += 1
                warnings.append(
                    f"Seed '{raw_seed}' has multiple identity candidates; confirmation is required."
                )

        if not seeds:
            raise ValueError("No seed paper could be resolved")

        def fetch_works(ids: list[str], source: str, reason: str, depth: int) -> None:
            nonlocal request_attempts
            check_deadline()
            ids = _unique(ids)
            if not ids or request_attempts >= self.config.max_http_attempts:
                return
            allowed = min(len(ids), target_pool - len(papers))
            ids = ids[: max(0, allowed)]
            if not ids:
                return
            fetched = self.provider.get_works(ids)
            request_attempts += (len(ids) + 99) // 100
            action = RetrievalAction(
                kind="references" if source == "historical_reference" else "identity_lookup",
                direction="backward",
                depth=depth,
                estimated_requests=(len(ids) + 99) // 100,
                reason=reason,
                result_count=len(fetched),
            )
            actions.append(action)
            for paper in fetched.values():
                add_paper(paper, source)

        seed_reference_ids: list[str] = []
        progress("retrieving direct references and citers")
        for seed_id in seeds:
            check_deadline()
            seed = papers[seed_id]
            seed_reference_ids.extend(seed.referenced_works)
            if request_attempts >= self.config.max_http_attempts:
                break
            citing = self.provider.citing_works(
                seed_id,
                limit=self.config.citing_limit,
                from_year=seed.year,
            )
            request_attempts += 1
            action = RetrievalAction(
                kind="citers",
                anchor_id=seed_id,
                direction="forward",
                reason="Direct forward citation neighborhood of a seed",
                result_count=len(citing),
            )
            actions.append(action)
            for paper in citing:
                add_paper(paper, "frontier", seed_id)

        seed_degree = len(set(seed_reference_ids)) + sum(
            1 for paper_id in papers if paper_id not in seeds
        )
        target_pool = self._adaptive_pool_target(
            seed_degree, len(seeds), self.config.max_display_nodes
        )
        fetch_works(
            seed_reference_ids,
            "foundation",
            "Direct backward citation neighborhood of the seeds",
            0,
        )

        progress("running short literature searches")
        queries = self._build_queries(papers, seeds)
        for query in queries[: self.config.max_text_queries]:
            check_deadline()
            if len(papers) >= target_pool:
                break
            if request_attempts >= self.config.max_http_attempts:
                warnings.append("Request budget exhausted during text search")
                break
            results = self.provider.search_works(
                query, limit=self.config.search_limit, sort="cited_by_count:desc"
            )
            request_attempts += 1
            kind = "survey_search" if _is_review_query(query) else "short_search"
            action = RetrievalAction(
                kind=kind,
                query=query,
                direction="discovery",
                reason="Field-independent short query derived from seed metadata",
                result_count=len(results),
            )
            actions.append(action)
            for paper in results:
                if len(papers) >= target_pool and paper.id not in seeds:
                    break
                add_paper(paper, "survey_search" if kind == "survey_search" else "text_search")

        # Select diverse anchors before historical expansion. This is lexical
        # MMR by design; embeddings are reserved for the later ranking stage.
        progress("selecting historical anchors")
        anchors = self._select_anchors(papers, seeds)
        for round_index in range(1, self.config.max_backward_rounds + 1):
            check_deadline()
            progress(f"backtracking history round {round_index}")
            reference_ids: list[str] = []
            for anchor_id in anchors:
                anchor = papers.get(anchor_id)
                if anchor:
                    reference_ids.extend(anchor.referenced_works)
            before = len(papers)
            fetch_works(
                reference_ids[: self.config.backfill_limit_per_round],
                "historical_reference",
                "Backward snowballing from diverse historical anchors",
                round_index,
            )
            if len(papers) == before:
                break
            anchors = self._select_anchors(papers, seeds)

        if len(papers) >= self.config.max_candidate_pool:
            warnings.append("Candidate pool cap reached; deeper expansion was stopped")
        if request_attempts >= self.config.max_http_attempts:
            warnings.append("HTTP request budget reached")

        progress("retrieval complete")

        return RetrievalResult(
            seeds=seeds,
            papers=papers,
            discovery=dict(discovery),
            actions=actions,
            warnings=warnings,
            stats={
                "raw_retrieved": len(papers),
                "resolved": resolved_count,
                "deduplicated": len(papers),
                "request_attempts": request_attempts,
                "max_http_attempts": self.config.max_http_attempts,
                "text_queries": len([a for a in actions if a.query]),
                "identity_conflicts": identity_conflicts,
                "candidate_pool_cap": self.config.max_candidate_pool,
                "adaptive_target_pool": target_pool,
                "max_backward_rounds": self.config.max_backward_rounds,
            },
        )

    @staticmethod
    def _adaptive_pool_target(seed_degree: int, seed_count: int, cap: int) -> int:
        """Give highly connected seeds more room without defaulting to 80."""
        import math

        target = 24 + int(8 * math.sqrt(max(0, seed_degree)))
        target += min(24, max(0, seed_count - 1) * 8)
        return max(seed_count + 1, min(cap, target))

    def _build_queries(self, papers: dict[str, Paper], seeds: list[str]) -> list[str]:
        terms: Counter[str] = Counter()
        phrases: Counter[str] = Counter()
        for paper_id in seeds:
            paper = papers[paper_id]
            tokens = _tokens(paper.title)
            for token in tokens:
                if token not in _STOPWORDS and len(token) >= 4:
                    terms[token] += 2
            for topic in paper.topics:
                for token in _tokens(topic):
                    if token not in _STOPWORDS and len(token) >= 4:
                        terms[token] += 1
            for left, right in zip(tokens, tokens[1:]):
                if left not in _STOPWORDS and right not in _STOPWORDS:
                    phrases[f"{left} {right}"] += 1

        queries: list[str] = []
        for phrase, _ in phrases.most_common(3):
            queries.append(phrase)
        for token, _ in terms.most_common(4):
            if token not in {part for query in queries for part in query.split()}:
                queries.append(token)
        base = queries[: max(1, self.config.max_text_queries // 2)]
        review = [f"{query} review" for query in base[:2]]
        return _unique([*base, *review])[: self.config.max_text_queries]

    def _select_anchors(self, papers: dict[str, Paper], seeds: list[str]) -> list[str]:
        candidates = [
            paper_id
            for paper_id in papers
            if paper_id not in seeds
            and not papers[paper_id].is_retracted
            and papers[paper_id].referenced_works
        ]
        candidates.sort(
            key=lambda paper_id: (
                papers[paper_id].year is None,
                -(papers[paper_id].cited_by_count or 0),
                paper_id,
            )
        )
        selected: list[str] = []
        selected_terms: list[set[str]] = []
        while candidates and len(selected) < self.config.anchor_limit:
            best = max(
                candidates,
                key=lambda paper_id: self._anchor_score(
                    papers[paper_id], selected_terms, seeds
                ),
            )
            selected.append(best)
            selected_terms.append(set(_tokens(papers[best].title)))
            candidates.remove(best)
        return selected

    @staticmethod
    def _anchor_score(
        paper: Paper, selected_terms: list[set[str]], seeds: list[str]
    ) -> float:
        terms = set(_tokens(paper.title))
        relevance = len(terms - _STOPWORDS) / max(len(terms), 1)
        novelty = 1.0
        if selected_terms and terms:
            novelty = 1.0 - max(
                _jaccard(terms, other) for other in selected_terms
            )
        influence = min(1.0, (paper.cited_by_count or 0) / 1000)
        return 0.55 * relevance + 0.30 * novelty + 0.15 * influence


def plan_and_execute(
    provider: PlannerProvider,
    seeds: list[str],
    config: HistoryPlannerConfig | None = None,
) -> RetrievalResult:
    return HistoryPlanner(provider, config).plan_and_execute(seeds)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9-]+", value.casefold())


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _is_review_query(query: str) -> bool:
    return any(token in query.casefold().split() for token in ("review", "survey", "overview"))


_STOPWORDS = {
    "a", "an", "and", "based", "by", "for", "from", "in", "into", "of",
    "on", "the", "to", "using", "with", "learning", "method", "methods",
    "model", "models", "prediction", "accurate", "highly", "new", "via",
}
