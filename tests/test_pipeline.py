from __future__ import annotations

from papernexus.models import Paper
from papernexus.pipeline import ResearchRoutePipeline


class FakeProvider:
    def __init__(self) -> None:
        self.papers = {
            "W1": Paper("W1", "Foundation", 2010, cited_by_count=1000),
            "W2": Paper("W2", "Seed", 2017, cited_by_count=500, referenced_works=["W1"]),
            "W3": Paper("W3", "Frontier", 2021, cited_by_count=50, referenced_works=["W2"]),
        }

    def resolve_seed(self, raw_seed: str):
        return self.papers["W2"], [self.papers["W2"]]

    def citing_works(self, work_id: str, limit=25, from_year=None, to_year=None):
        return [self.papers["W3"]]

    def get_works(self, work_ids):
        return {work_id: self.papers[work_id] for work_id in work_ids}

    def search_works(self, query, limit=10, sort=None):
        return []


def test_pipeline_builds_confirmed_route():
    result = ResearchRoutePipeline(FakeProvider()).build(["seed"], max_nodes=10)
    assert result.seeds == ["W2"]
    assert result.routes[0].paper_ids == ["W1", "W2", "W3"]
    assert len(result.reading_list) == 3
    assert result.provenance["algorithm_version"] == "prototype-0.2"
    assert result.candidates["W1"].shared_reference_count == 0
    assert result.candidates["W1"].historical_rank == 1
    edge = next(item for item in result.edges if item["source"] == "W1")
    assert 0.0 < edge["display_weight"] <= edge["evidence_weight"] <= 1.0
