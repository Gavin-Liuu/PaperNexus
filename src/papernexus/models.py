from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass(slots=True)
class Paper:
    id: str
    title: str
    year: int | None
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    cited_by_count: int = 0
    fwci: float | None = None
    citation_percentile: float | None = None
    referenced_works: list[str] = field(default_factory=list)
    abstract: str | None = None
    topics: list[str] = field(default_factory=list)
    is_retracted: bool = False
    oa_url: str | None = None
    source: str = "openalex"
    updated_at: str | None = None
    related_works: list[str] = field(default_factory=list)
    document_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Paper:
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in allowed})


@dataclass(slots=True)
class CandidateEvidence:
    paper_id: str
    roles: set[str] = field(default_factory=set)
    seed_links: set[str] = field(default_factory=set)
    citation_edges: set[tuple[str, str]] = field(default_factory=set)
    shared_reference_count: int = 0
    historical_rank: int | None = None
    shared_seed_count: int = 0
    relevance_score: float = 0.0
    semantic_score: float = 0.0
    influence_score: float = 0.0
    bridge_score: float = 0.0
    route_score: float = 0.0
    selection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["roles"] = sorted(self.roles)
        data["seed_links"] = sorted(self.seed_links)
        data["citation_edges"] = [
            {"source": source, "target": target, "type": "citation"}
            for source, target in sorted(self.citation_edges)
        ]
        return data


@dataclass(slots=True)
class Route:
    id: str
    paper_ids: list[str]
    score: float
    evidence_status: str
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReadingItem:
    paper_id: str
    tier: str
    reason: str
    connected_to: list[str]
    evidence_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResearchRouteResult:
    seeds: list[str]
    papers: dict[str, Paper]
    edges: list[dict[str, Any]]
    candidates: dict[str, CandidateEvidence]
    routes: list[Route]
    reading_list: list[ReadingItem]
    provenance: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seeds": self.seeds,
            "papers": {paper_id: paper.to_dict() for paper_id, paper in self.papers.items()},
            "edges": self.edges,
            "candidates": {
                paper_id: evidence.to_dict()
                for paper_id, evidence in self.candidates.items()
            },
            "routes": [route.to_dict() for route in self.routes],
            "reading_list": [item.to_dict() for item in self.reading_list],
            "provenance": self.provenance,
            "warnings": self.warnings,
        }
