from __future__ import annotations

import numpy as np

from papernexus.models import Paper
from papernexus.filtering import rank_candidates
from papernexus.ranking import (
    directional_quota_rank,
    reciprocal_rank_fusion,
    relation_scores,
    semantic_scores,
)


class FakeEmbedder:
    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            [[1.0, 0.0] if "metalens" in text.casefold() else [0.0, 1.0] for text in texts]
        )


def test_relation_scores_compute_coupling_and_local_cocitation():
    papers = {
        "S": Paper("S", "Seed metalens", 2020, referenced_works=["R1", "R2"]),
        "A": Paper("A", "Related metalens", 2021, referenced_works=["S", "R1"]),
        "C": Paper("C", "Citer", 2022, referenced_works=["S", "A"]),
    }
    scores = relation_scores(papers, {"S"})
    assert scores["A"]["citation"] == 1.0
    assert scores["A"]["descendant"] == 1.0
    assert scores["A"]["ancestor"] == 0.0
    assert scores["A"]["coupling"] > 0
    assert 0 < scores["A"]["cocitation"] < 1.0


def test_semantic_scores_and_rrf():
    papers = {
        "S": Paper("S", "Seed metalens", 2020),
        "A": Paper("A", "Related metalens", 2021),
        "B": Paper("B", "Unrelated battery", 2021),
    }
    semantic, _ = semantic_scores(papers, {"S"}, FakeEmbedder())
    fused = reciprocal_rank_fusion(
        [(semantic, 1.0), ({"A": 1.0, "B": 0.0}, 1.0)], excluded={"S"}
    )
    assert semantic["A"] > semantic["B"]
    assert fused["A"] > fused.get("B", 0.0)


def test_directional_quota_preserves_ancestors_and_descendants():
    fused = {"A": 0.2, "D": 0.3, "S": 1.0, "X": 0.9}
    relations = {
        "A": {"ancestor": 1.0, "descendant": 0.0},
        "D": {"ancestor": 0.0, "descendant": 1.0},
        "S": {"ancestor": 0.0, "descendant": 0.0},
        "X": {"ancestor": 0.0, "descendant": 0.0},
    }
    ranked = directional_quota_rank(fused, relations, excluded={"S"}, quota_per_direction=1)
    assert ranked[:2] == ["A", "D"]


def test_two_stage_candidate_filter_returns_explainable_tiers():
    papers = {
        "S": Paper("S", "Seed metalens", 2020),
        "A": Paper("A", "Achromatic metalens imaging", 2021, referenced_works=["S"]),
        "B": Paper("B", "Unrelated battery chemistry", 2021),
    }
    ranked = rank_candidates(
        papers,
        ["A", "B"],
        "metalens imaging",
        FakeEmbedder(),
        anchor_ids={"S"},
        coarse_limit=2,
        limit=2,
    )
    assert ranked[0].paper_id == "A"
    assert ranked[0].tier == "verified"
    assert any("citation" in reason.casefold() for reason in ranked[0].reasons)


def test_candidate_filter_collapses_preprint_and_published_title_versions():
    papers = {
        "P": Paper("P", "A Metalens Result", 2021, cited_by_count=2),
        "J": Paper("J", "A Metalens Result", 2022, cited_by_count=20),
    }
    ranked = rank_candidates(
        papers,
        ["P", "J"],
        "metalens",
        FakeEmbedder(),
        coarse_limit=2,
        limit=2,
    )
    assert [item.paper_id for item in ranked] == ["J"]
