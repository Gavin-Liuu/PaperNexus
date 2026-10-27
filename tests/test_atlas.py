from __future__ import annotations

import numpy as np
import pytest

from papernexus.atlas import BranchExpansion, LazyAtlas, collect_related_halo
from papernexus.branching import DiscoveredBranch
from papernexus.models import Paper


class CountingEmbedder:
    def __init__(self) -> None:
        self.calls = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        vectors = []
        for index, _ in enumerate(texts):
            vector = np.zeros(8, dtype=float)
            vector[index % 2] = 1.0
            vectors.append(vector)
        return np.asarray(vectors)


class KeywordEmbedder:
    def __init__(self) -> None:
        self.cache_hits = 0
        self.cache_misses = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            [
                [1.0, 0.0]
                if "metalens" in text.casefold()
                else [0.0, 1.0]
                for text in texts
            ]
        )


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search_works(self, query: str, limit: int = 50) -> list[Paper]:
        self.calls.append(query)
        return [Paper(f"R{len(self.calls)}", f"Remote {query}", 2024)]


class FakeHaloProvider:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def get_works(self, work_ids):
        self.requested = list(work_ids)
        return {
            paper_id: Paper(paper_id, f"Related {paper_id}", 2022)
            for paper_id in self.requested
        }


class FailingProvider:
    def search_works(self, query: str, limit: int = 50) -> list[Paper]:
        raise ConnectionError("remote search failed")


class MappingHaloProvider:
    def __init__(self, papers: dict[str, Paper]) -> None:
        self.papers = papers
        self.batches: list[list[str]] = []

    def get_works(self, work_ids):
        batch = list(work_ids)
        self.batches.append(batch)
        return {
            paper_id: self.papers[paper_id]
            for paper_id in batch
            if paper_id in self.papers
        }


def test_build_reuses_vectors_for_branch_discovery():
    papers = {
        f"W{index}": Paper(f"W{index}", f"Metalens topic {index % 2}", 2020 + index)
        for index in range(8)
    }
    core = {
        "seeds": ["W0"],
        "papers": {"W0": papers["W0"].to_dict()},
    }
    embedder = CountingEmbedder()
    atlas = LazyAtlas.build(
        core, papers, embedder, halo_limit=8, branch_limit=4
    )
    assert len(atlas.papers) == 8
    assert embedder.calls == 1


def test_preview_local_activation_and_remote_budget_round_trip():
    papers = {
        "S": Paper("S", "Seed", 2020),
        "A": Paper("A", "Local candidate", 2021, cited_by_count=5),
    }
    branch = DiscoveredBranch(
        id="branch-test",
        label="wide field",
        query="metalens wide field",
        queries=["metalens wide field", "metalens fisheye"],
        paper_ids=["S", "A"],
        representative_ids=["A"],
        core_paper_count=1,
        frontier_paper_count=1,
        year_min=2020,
        year_max=2021,
        semantic_coherence=0.8,
    )
    atlas = LazyAtlas(
        seeds=["S"],
        core_ids=["S"],
        papers=papers,
        branches=[branch],
        query_budget_total=1,
    )
    preview = atlas.preview_branch("branch-test")
    assert preview["papers"][0]["id"] == "A"
    assert preview["remote_query_required"]
    assert atlas.query_budget_used == 0

    atlas.activate_local("branch-test")
    assert atlas.query_budget_used == 0
    provider = FakeProvider()
    atlas.expand_remote("branch-test", provider)
    assert provider.calls == ["metalens wide field"]
    assert atlas.query_budget_remaining == 0

    restored = LazyAtlas.from_dict(atlas.to_dict())
    assert restored.expansions["branch-test"].remote_paper_ids == ["R1"]
    assert restored.preview_branch("branch-test")["papers"][0]["id"] == "A"


def test_remote_failure_does_not_consume_budget_or_mutate_atlas():
    branch = DiscoveredBranch(
        id="branch-test",
        label="wide field",
        query="metalens wide field",
        queries=["metalens wide field"],
        paper_ids=["S"],
        representative_ids=[],
        core_paper_count=1,
        frontier_paper_count=0,
        year_min=2020,
        year_max=2020,
        semantic_coherence=1.0,
    )
    atlas = LazyAtlas(
        seeds=["S"],
        core_ids=["S"],
        papers={"S": Paper("S", "Seed", 2020)},
        branches=[branch],
        query_budget_total=1,
    )

    with pytest.raises(ConnectionError, match="remote search failed"):
        atlas.expand_remote("branch-test", FailingProvider())

    assert atlas.query_budget_used == 0
    assert atlas.query_budget_remaining == 1
    assert atlas.expansions == {}
    assert set(atlas.papers) == {"S"}


def test_remote_ranking_persists_and_preview_hides_unverified_candidates():
    papers = {
        "S": Paper("S", "Seed metalens", 2020),
        "A": Paper("A", "Metalens display", 2022, referenced_works=["S"]),
        "B": Paper("B", "Battery chemistry", 2022),
    }
    branch = DiscoveredBranch(
        id="branch-test",
        label="display",
        query="metalens display",
        queries=["metalens display"],
        paper_ids=["S"],
        representative_ids=[],
        core_paper_count=1,
        frontier_paper_count=0,
        year_min=2020,
        year_max=2020,
        semantic_coherence=1.0,
    )
    atlas = LazyAtlas(
        seeds=["S"],
        core_ids=["S"],
        papers=papers,
        branches=[branch],
        expansions={
            "branch-test": BranchExpansion(
                branch_id="branch-test", remote_paper_ids=["A", "B"]
            )
        },
    )

    expansion = atlas.rank_remote(
        "branch-test", KeywordEmbedder(), coarse_limit=2, limit=2
    )
    assert [item.paper_id for item in expansion.remote_ranking] == ["A", "B"]
    assert expansion.remote_ranking[0].tier == "verified"
    assert expansion.remote_ranking[1].tier == "candidate"

    preview = atlas.preview_branch("branch-test")
    assert [paper["id"] for paper in preview["remote_papers"]] == ["A"]
    assert not preview["remote_ranking_required"]

    restored = LazyAtlas.from_dict(atlas.to_dict())
    assert restored.schema_version == 2
    assert restored.expansions["branch-test"].remote_ranking[0].paper_id == "A"

    atlas.expand_remote("branch-test", FakeProvider())
    assert atlas.expansions["branch-test"].remote_ranking == []
    assert atlas.expansions["branch-test"].ranked_at is None


def test_collect_related_halo_batches_shared_anchor_candidates():
    core = {
        "seeds": ["S"],
        "papers": {
            "S": Paper("S", "Seed", 2020, related_works=["R1", "R2"]).to_dict(),
            "A": Paper("A", "Route", 2021, related_works=["R1", "R3"]).to_dict(),
        },
        "routes": [{"paper_ids": ["S", "A"]}],
        "reading_list": [],
    }
    provider = FakeHaloProvider()
    halo, stats = collect_related_halo(core, provider)
    assert provider.requested[0] == "R1"
    assert set(halo) == {"S", "A", "R1", "R2", "R3"}
    assert stats["estimated_batch_calls"] == 1


def test_collect_related_halo_refreshes_legacy_anchors_without_related_works():
    core = {
        "seeds": ["S"],
        "papers": {"S": Paper("S", "Legacy seed", 2020).to_dict()},
        "routes": [],
        "reading_list": [],
    }
    provider = MappingHaloProvider(
        {
            "S": Paper("S", "Refreshed seed", 2020, related_works=["R1"]),
            "R1": Paper("R1", "Related paper", 2021),
        }
    )

    halo, stats = collect_related_halo(core, provider)

    assert provider.batches == [["S"], ["R1"]]
    assert set(halo) == {"S", "R1"}
    assert halo["S"].related_works == ["R1"]
    assert stats["anchors_refreshed"] == 1
    assert stats["anchor_refresh_batch_calls"] == 1
