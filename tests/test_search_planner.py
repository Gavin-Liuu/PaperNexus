from papernexus.models import Paper
from papernexus.search_planner import HistoryPlanner, HistoryPlannerConfig


class PlannerProvider:
    def __init__(self):
        self.papers = {
            "S": Paper(
                "S",
                "Advanced optical imaging",
                2020,
                topics=["Optical Imaging", "Computational Methods"],
                referenced_works=["A", "B"],
            ),
            "A": Paper("A", "Early optical foundations", 2010, referenced_works=["F"]),
            "B": Paper("B", "Computational imaging review", 2018, referenced_works=["F"]),
            "F": Paper("F", "Foundational optics", 1990),
            "C": Paper("C", "A later optical advance", 2022, referenced_works=["S"]),
        }
        self.queries = []

    def resolve_seed(self, raw_seed):
        return self.papers["S"], [self.papers["S"]]

    def get_works(self, work_ids):
        return {paper_id: self.papers[paper_id] for paper_id in work_ids if paper_id in self.papers}

    def citing_works(self, work_id, limit=25, from_year=None, to_year=None):
        return [self.papers["C"]]

    def search_works(self, query, limit=10, sort=None):
        self.queries.append(query)
        return [self.papers["B"]]


def test_planner_uses_short_queries_and_bounded_backtracking():
    provider = PlannerProvider()
    result = HistoryPlanner(
        provider,
        HistoryPlannerConfig(max_backward_rounds=2, max_text_queries=6, max_http_attempts=30),
    ).plan_and_execute(["seed"])

    assert result.seeds == ["S"]
    assert {"S", "A", "B", "C", "F"} <= set(result.papers)
    assert all(len(query.split()) <= 4 for query in provider.queries)
    assert len(provider.queries) <= 6
    assert result.stats["request_attempts"] <= 30
    assert result.stats["adaptive_target_pool"] < 80
    assert any(action.kind == "references" for action in result.actions)


def test_planner_records_discovery_and_does_not_claim_semantic_edges_as_citations():
    result = HistoryPlanner(PlannerProvider()).plan_and_execute(["seed"])

    assert "seed" in result.discovery["S"]
    assert "frontier" in result.discovery["C"]
    assert all(action.kind != "semantic_edge" for action in result.actions)
