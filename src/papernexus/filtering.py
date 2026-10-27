from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

import numpy as np

from .models import Paper
from .ranking import (
    TextEmbedder,
    paper_text,
    reciprocal_rank_fusion,
    relation_scores,
)


@dataclass(slots=True)
class RankedCandidate:
    paper_id: str
    coarse_score: float
    full_score: float
    citation_score: float
    coupling_score: float
    cocitation_score: float
    final_score: float
    tier: str
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def short_paper_text(paper: Paper) -> str:
    topics = "; ".join(paper.topics)
    return f"Title: {paper.title}\nTopics: {topics}".strip()


def rank_candidates(
    papers: dict[str, Paper],
    candidate_ids: list[str],
    query: str,
    embedder: TextEmbedder,
    anchor_ids: set[str] | None = None,
    coarse_limit: int = 50,
    limit: int = 20,
) -> list[RankedCandidate]:
    """Use cheap title/topic embeddings before expensive abstract embeddings."""
    candidate_ids = _deduplicate_candidates(papers, candidate_ids)
    if not candidate_ids:
        return []
    coarse_limit = max(limit, coarse_limit)
    coarse_vectors = embedder.embed(
        [query, *[short_paper_text(papers[paper_id]) for paper_id in candidate_ids]]
    )
    coarse_query = coarse_vectors[0]
    coarse_scores = coarse_vectors[1:] @ coarse_query
    coarse_order = np.argsort(coarse_scores)[::-1][:coarse_limit]
    shortlist = [candidate_ids[index] for index in coarse_order]

    full_vectors = embedder.embed(
        [query, *[paper_text(papers[paper_id]) for paper_id in shortlist]]
    )
    full_query = full_vectors[0]
    full_scores = full_vectors[1:] @ full_query
    coarse_by_id = {
        paper_id: float(coarse_scores[index])
        for index, paper_id in enumerate(candidate_ids)
        if paper_id in shortlist
    }
    full_by_id = {
        paper_id: float(full_scores[index])
        for index, paper_id in enumerate(shortlist)
    }
    relations = relation_scores(papers, anchor_ids or set()) if anchor_ids else {}
    citation_scores = {
        paper_id: float(relations.get(paper_id, {}).get("citation", 0.0))
        for paper_id in shortlist
    }
    coupling_scores = {
        paper_id: float(relations.get(paper_id, {}).get("coupling", 0.0))
        for paper_id in shortlist
    }
    cocitation_scores = {
        paper_id: float(relations.get(paper_id, {}).get("cocitation", 0.0))
        for paper_id in shortlist
    }
    fused_scores = reciprocal_rank_fusion(
        [
            (full_by_id, 1.0),
            (coarse_by_id, 0.4),
            (citation_scores, 0.8),
            (coupling_scores, 0.5),
            (cocitation_scores, 0.5),
        ],
        rank_constant=20,
    )

    ranked: list[RankedCandidate] = []
    for paper_id in shortlist:
        relation = relations.get(paper_id, {})
        citation = float(relation.get("citation", 0.0))
        coupling = float(relation.get("coupling", 0.0))
        cocitation = float(relation.get("cocitation", 0.0))
        final_score = fused_scores.get(paper_id, 0.0)
        if relation.get("ancestor", 0.0) > 0 and relation.get("descendant", 0.0) > 0:
            tier = "bridge"
        elif citation > 0 or coupling > 0 or cocitation > 0:
            tier = "verified"
        else:
            tier = "candidate"
        reasons = [f"Semantic match {full_by_id[paper_id]:.2f}"]
        if citation > 0:
            reasons.append("Connected by a citation path to an anchor")
        if coupling > 0:
            reasons.append("Shares references with an anchor")
        if cocitation > 0:
            reasons.append("Shares citing works with an anchor")
        if tier == "bridge":
            reasons.append("Connects earlier and later anchor-connected work")
        ranked.append(
            RankedCandidate(
                paper_id=paper_id,
                coarse_score=round(coarse_by_id[paper_id], 4),
                full_score=round(full_by_id[paper_id], 4),
                citation_score=round(citation, 4),
                coupling_score=round(coupling, 4),
                cocitation_score=round(cocitation, 4),
                final_score=round(final_score, 4),
                tier=tier,
                reasons=reasons,
            )
        )
    return sorted(ranked, key=lambda item: (item.final_score, item.paper_id), reverse=True)[:limit]


def _deduplicate_candidates(
    papers: dict[str, Paper], candidate_ids: list[str]
) -> list[str]:
    eligible = set(item for item in candidate_ids if item in papers)
    ordered = sorted(
        eligible,
        key=lambda paper_id: (
            papers[paper_id].cited_by_count,
            papers[paper_id].citation_percentile or 0.0,
            bool(papers[paper_id].abstract),
            bool(papers[paper_id].doi),
            papers[paper_id].year or 0,
        ),
        reverse=True,
    )
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    selected: list[str] = []
    for paper_id in ordered:
        paper = papers[paper_id]
        doi = _normalize_doi(paper.doi)
        title = re.sub(r"[^a-z0-9]+", " ", paper.title.casefold()).strip()
        if (doi and doi in seen_dois) or (title and title in seen_titles):
            continue
        selected.append(paper_id)
        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.add(title)
    return selected


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"^(?:https?://doi\.org/|doi:\s*)", "", value.casefold()).rstrip(". ")
