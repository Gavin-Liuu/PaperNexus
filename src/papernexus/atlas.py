from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from collections import Counter
import time
from typing import Any, Iterable, Protocol

from .branching import DiscoveredBranch, discover_branches, infer_query_prefix
from .filtering import RankedCandidate, rank_candidates
from .models import Paper
from .ranking import FastEmbedder, TextEmbedder, semantic_scores


class BranchSearchProvider(Protocol):
    def search_works(self, query: str, limit: int = 50) -> list[Paper]: ...


class HaloProvider(Protocol):
    def get_works(self, work_ids: Iterable[str]) -> dict[str, Paper]: ...


@dataclass(slots=True)
class BranchExpansion:
    branch_id: str
    local_paper_ids: list[str] = field(default_factory=list)
    remote_paper_ids: list[str] = field(default_factory=list)
    queries_used: list[str] = field(default_factory=list)
    remote_ranking: list[RankedCandidate] = field(default_factory=list)
    ranking_query: str | None = None
    ranking_model: str | None = None
    ranking_elapsed_seconds: float | None = None
    ranking_cache_hits: int = 0
    ranking_cache_misses: int = 0
    ranked_at: str | None = None
    activated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(slots=True)
class LazyAtlas:
    seeds: list[str]
    core_ids: list[str]
    papers: dict[str, Paper]
    branches: list[DiscoveredBranch]
    query_budget_total: int = 8
    query_budget_used: int = 0
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_hits: int = 0
    embedding_cache_misses: int = 0
    expansions: dict[str, BranchExpansion] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: int = 2

    @property
    def query_budget_remaining(self) -> int:
        return max(0, self.query_budget_total - self.query_budget_used)

    @classmethod
    def build(
        cls,
        core_result: dict[str, Any],
        halo_papers: dict[str, Paper],
        embedder: TextEmbedder,
        halo_limit: int = 250,
        branch_limit: int = 12,
        query_budget: int = 8,
        embedding_model: str = "BAAI/bge-small-en-v1.5",
    ) -> LazyAtlas:
        core_papers = {
            paper_id: Paper.from_dict(paper)
            for paper_id, paper in core_result["papers"].items()
        }
        seed_ids = set(core_result["seeds"])
        combined = dict(core_papers)
        combined.update(halo_papers)
        semantic, vectors = semantic_scores(combined, seed_ids, embedder)
        frontier_ids = sorted(
            (paper_id for paper_id in combined if paper_id not in core_papers),
            key=lambda paper_id: semantic[paper_id],
            reverse=True,
        )[: max(0, halo_limit - len(core_papers))]
        selected = {
            paper_id: combined[paper_id]
            for paper_id in [*core_papers, *frontier_ids]
        }
        selected_vectors = {
            paper_id: vectors[paper_id] for paper_id in selected
        }
        branches = discover_branches(
            selected,
            set(core_papers),
            embedder,
            vectors_by_id=selected_vectors,
            query_prefix=infer_query_prefix(selected, seed_ids),
        )[:branch_limit]
        return cls(
            seeds=list(core_result["seeds"]),
            core_ids=list(core_papers),
            papers=selected,
            branches=branches,
            query_budget_total=query_budget,
            embedding_model=embedding_model,
            embedding_cache_hits=getattr(embedder, "cache_hits", 0),
            embedding_cache_misses=getattr(embedder, "cache_misses", 0),
        )

    def preview_branch(self, branch_id: str, limit: int = 10) -> dict[str, Any]:
        branch = self._branch(branch_id)
        expansion = self.expansions.get(branch_id)
        core_ids = set(self.core_ids)
        frontier_ids = [
            paper_id for paper_id in branch.paper_ids if paper_id not in core_ids
        ]
        ordered = _unique(
            [
                *(
                    paper_id
                    for paper_id in branch.representative_ids
                    if paper_id in frontier_ids
                ),
                *sorted(
                    frontier_ids,
                    key=lambda paper_id: (
                        self.papers[paper_id].cited_by_count,
                        self.papers[paper_id].year or 0,
                    ),
                    reverse=True,
                ),
            ]
        )[:limit]
        remote_ranking = expansion.remote_ranking if expansion else []
        visible_remote = [
            item for item in remote_ranking if item.tier in {"verified", "bridge"}
        ][:limit]
        return {
            "branch": branch.to_dict(),
            "local_candidate_count": len(frontier_ids),
            "remote_candidate_count": len(expansion.remote_paper_ids) if expansion else 0,
            "remote_ranked_count": len(remote_ranking),
            "remote_visible_count": len(visible_remote),
            "remote_query_required": len(frontier_ids) < limit
            and not (expansion and expansion.remote_paper_ids),
            "remote_ranking_required": bool(
                expansion and expansion.remote_paper_ids and not remote_ranking
            ),
            "query_budget_remaining": self.query_budget_remaining,
            "papers": [self.papers[paper_id].to_dict() for paper_id in ordered],
            "remote_papers": [
                {
                    **self.papers[item.paper_id].to_dict(),
                    "evidence": item.to_dict(),
                }
                for item in visible_remote
            ],
        }

    def activate_local(self, branch_id: str, limit: int = 20) -> BranchExpansion:
        preview = self.preview_branch(branch_id, limit=limit)
        paper_ids = [paper["id"] for paper in preview["papers"]]
        expansion = self.expansions.setdefault(
            branch_id, BranchExpansion(branch_id=branch_id)
        )
        expansion.local_paper_ids = _unique(
            [*expansion.local_paper_ids, *paper_ids]
        )
        self.updated_at = datetime.now(UTC).isoformat()
        return expansion

    def expand_remote(
        self,
        branch_id: str,
        provider: BranchSearchProvider,
        max_queries: int = 1,
        results_per_query: int = 50,
    ) -> BranchExpansion:
        branch = self._branch(branch_id)
        remaining_queries = [
            query
            for query in branch.queries
            if query not in self.expansions.get(
                branch_id, BranchExpansion(branch_id)
            ).queries_used
        ]
        allowed = min(max_queries, self.query_budget_remaining, len(remaining_queries))
        if allowed <= 0:
            raise RuntimeError("No remote query budget remains for this branch")

        for query in remaining_queries[:allowed]:
            papers = provider.search_works(query, limit=results_per_query)
            fetched = {paper.id: paper for paper in papers}
            expansion = self.expansions.setdefault(
                branch_id, BranchExpansion(branch_id=branch_id)
            )
            expansion.queries_used.append(query)
            self.query_budget_used += 1
            self._invalidate_remote_ranking(expansion)
            for paper_id, paper in fetched.items():
                self.papers.setdefault(paper_id, paper)
                if paper_id not in expansion.remote_paper_ids:
                    expansion.remote_paper_ids.append(paper_id)
        self.updated_at = datetime.now(UTC).isoformat()
        return self.expansions[branch_id]

    def rank_remote(
        self,
        branch_id: str,
        embedder: TextEmbedder,
        coarse_limit: int = 50,
        limit: int = 20,
        model_name: str | None = None,
    ) -> BranchExpansion:
        branch = self._branch(branch_id)
        expansion = self.expansions.get(branch_id)
        if not expansion or not expansion.remote_paper_ids:
            raise RuntimeError(f"Branch has no remote candidates: {branch_id}")

        cache_hits_before = int(getattr(embedder, "cache_hits", 0))
        cache_misses_before = int(getattr(embedder, "cache_misses", 0))
        started = time.perf_counter()
        ranking = rank_candidates(
            self.papers,
            expansion.remote_paper_ids,
            branch.query,
            embedder,
            anchor_ids=set(branch.paper_ids),
            coarse_limit=coarse_limit,
            limit=limit,
        )
        elapsed = time.perf_counter() - started

        expansion.remote_ranking = ranking
        expansion.ranking_query = branch.query
        expansion.ranking_model = model_name or self.embedding_model
        expansion.ranking_elapsed_seconds = round(elapsed, 4)
        expansion.ranking_cache_hits = int(
            getattr(embedder, "cache_hits", 0)
        ) - cache_hits_before
        expansion.ranking_cache_misses = int(
            getattr(embedder, "cache_misses", 0)
        ) - cache_misses_before
        expansion.ranked_at = datetime.now(UTC).isoformat()
        self.updated_at = expansion.ranked_at
        return expansion

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "seeds": self.seeds,
            "core_ids": self.core_ids,
            "papers": {
                paper_id: paper.to_dict() for paper_id, paper in self.papers.items()
            },
            "branches": [branch.to_dict() for branch in self.branches],
            "query_budget_total": self.query_budget_total,
            "query_budget_used": self.query_budget_used,
            "query_budget_remaining": self.query_budget_remaining,
            "embedding_model": self.embedding_model,
            "embedding_cache_hits": self.embedding_cache_hits,
            "embedding_cache_misses": self.embedding_cache_misses,
            "expansions": {
                branch_id: asdict(expansion)
                for branch_id, expansion in self.expansions.items()
            },
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LazyAtlas:
        return cls(
            seeds=list(raw["seeds"]),
            core_ids=list(raw["core_ids"]),
            papers={
                paper_id: Paper.from_dict(paper)
                for paper_id, paper in raw["papers"].items()
            },
            branches=[DiscoveredBranch(**branch) for branch in raw["branches"]],
            query_budget_total=int(raw["query_budget_total"]),
            query_budget_used=int(raw.get("query_budget_used", 0)),
            embedding_model=raw.get("embedding_model", "BAAI/bge-small-en-v1.5"),
            embedding_cache_hits=int(raw.get("embedding_cache_hits", 0)),
            embedding_cache_misses=int(raw.get("embedding_cache_misses", 0)),
            expansions={
                branch_id: _expansion_from_dict(expansion)
                for branch_id, expansion in raw.get("expansions", {}).items()
            },
            warnings=list(raw.get("warnings", [])),
            created_at=raw.get("created_at", datetime.now(UTC).isoformat()),
            updated_at=raw.get("updated_at", datetime.now(UTC).isoformat()),
            schema_version=max(2, int(raw.get("schema_version", 1))),
        )

    def _branch(self, branch_id: str) -> DiscoveredBranch:
        for branch in self.branches:
            if branch.id == branch_id:
                return branch
        raise KeyError(f"Unknown branch: {branch_id}")

    @staticmethod
    def _invalidate_remote_ranking(expansion: BranchExpansion) -> None:
        expansion.remote_ranking = []
        expansion.ranking_query = None
        expansion.ranking_model = None
        expansion.ranking_elapsed_seconds = None
        expansion.ranking_cache_hits = 0
        expansion.ranking_cache_misses = 0
        expansion.ranked_at = None


def load_halo_papers(raw: dict[str, Any]) -> dict[str, Paper]:
    paper_data = raw.get("papers", raw)
    return {
        paper_id: Paper.from_dict(paper) for paper_id, paper in paper_data.items()
    }


def collect_related_halo(
    core_result: dict[str, Any],
    provider: HaloProvider,
    max_related_ids: int = 300,
) -> tuple[dict[str, Paper], dict[str, int]]:
    core_papers = {
        paper_id: Paper.from_dict(paper)
        for paper_id, paper in core_result["papers"].items()
    }
    anchor_ids = _unique(
        [
            *core_result["seeds"],
            *(
                paper_id
                for route in core_result.get("routes", [])
                for paper_id in route.get("paper_ids", [])
            ),
            *(
                item["paper_id"]
                for item in core_result.get("reading_list", [])
                if "paper_id" in item
            ),
        ]
    )
    anchors_to_refresh = [
        paper_id
        for paper_id in anchor_ids
        if paper_id in core_papers and not core_papers[paper_id].related_works
    ]
    refreshed_anchors = (
        provider.get_works(anchors_to_refresh) if anchors_to_refresh else {}
    )
    for paper_id, paper in refreshed_anchors.items():
        if paper_id in core_papers:
            core_papers[paper_id] = paper

    related_frequency: Counter[str] = Counter()
    for paper_id in anchor_ids:
        paper = core_papers.get(paper_id)
        if paper:
            related_frequency.update(paper.related_works)
    related_ids = [
        paper_id
        for paper_id, _ in related_frequency.most_common(max_related_ids)
        if paper_id not in core_papers
    ]
    fetched = provider.get_works(related_ids) if related_ids else {}
    combined = dict(core_papers)
    combined.update(fetched)
    return combined, {
        "anchor_count": len(anchor_ids),
        "anchors_refreshed": len(refreshed_anchors),
        "anchor_refresh_batch_calls": (len(anchors_to_refresh) + 99) // 100,
        "related_ids_requested": len(related_ids),
        "related_papers_fetched": len(fetched),
        "estimated_batch_calls": (len(related_ids) + 99) // 100,
    }


def default_embedder(model_name: str = "BAAI/bge-small-en-v1.5") -> FastEmbedder:
    return FastEmbedder(model_name=model_name)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _expansion_from_dict(raw: dict[str, Any]) -> BranchExpansion:
    data = dict(raw)
    data["remote_ranking"] = [
        RankedCandidate(**item) for item in data.get("remote_ranking", [])
    ]
    return BranchExpansion(**data)
