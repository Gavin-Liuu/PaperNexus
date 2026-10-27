from __future__ import annotations

from papernexus.models import CandidateEvidence, Paper
from papernexus.routing import (
    assign_roles,
    build_influence_graph,
    build_reading_list,
    extract_routes,
    score_candidates,
)


def fixture_graph():
    papers = {
        "W1": Paper("W1", "Foundation", 2010, cited_by_count=1000),
        "W2": Paper("W2", "Bridge", 2014, cited_by_count=100, referenced_works=["W1"]),
        "W3": Paper("W3", "Seed", 2017, cited_by_count=500, referenced_works=["W2"]),
        "W4": Paper("W4", "Frontier", 2020, cited_by_count=80, referenced_works=["W3"]),
        "W5": Paper("W5", "Branch", 2021, cited_by_count=10, referenced_works=["W3"]),
    }
    candidates = {
        paper_id: CandidateEvidence(paper_id=paper_id) for paper_id in papers
    }
    candidates["W3"].seed_links.add("W3")
    for paper_id in ("W1", "W2"):
        candidates[paper_id].seed_links.add("W3")
        candidates[paper_id].roles.add("foundation")
    for paper_id in ("W4", "W5"):
        candidates[paper_id].seed_links.add("W3")
        candidates[paper_id].roles.add("frontier")
    graph, edges = build_influence_graph(papers)
    return papers, candidates, graph, edges


def test_build_influence_graph_reverses_raw_citation_direction():
    _, _, graph, edges = fixture_graph()
    assert graph.has_edge("W1", "W2")
    assert graph.has_edge("W2", "W3")
    assert graph.has_edge("W3", "W4")
    assert edges[0]["raw_direction"] == "W2->W1"


def test_extract_route_and_reading_list():
    papers, candidates, graph, _ = fixture_graph()
    seeds = {"W3"}
    assign_roles(papers, graph, candidates, seeds)
    score_candidates(papers, graph, candidates, seeds)
    routes = extract_routes(graph, candidates, seeds, max_routes=2)
    assert routes
    assert routes[0].paper_ids[0] in {"W1", "W2"}
    assert "W3" in routes[0].paper_ids
    reading = build_reading_list(papers, candidates, seeds, routes)
    assert reading[0].tier == "read_first"
    assert reading[0].evidence_status == "user_provided_seed"
    assert any(item.tier == "background" for item in reading)
    assert any(item.tier == "frontier" for item in reading)


def test_future_dated_reference_is_not_used_as_influence_edge():
    papers = {
        "W1": Paper("W1", "Earlier", 2010, referenced_works=["W2"]),
        "W2": Paper("W2", "Later", 2020),
    }
    graph, edges = build_influence_graph(papers)
    assert graph.number_of_edges() == 0
    assert edges == []


def test_non_route_turning_point_is_not_forced_into_read_first():
    papers, candidates, graph, _ = fixture_graph()
    candidates["W2"].roles.add("turning_point")
    routes = [
        type("RouteLike", (), {"paper_ids": ["W1", "W3", "W4"]})()
    ]
    score_candidates(papers, graph, candidates, {"W3"})
    reading = build_reading_list(papers, candidates, {"W3"}, routes)
    w2 = next(item for item in reading if item.paper_id == "W2")
    assert w2.tier == "background"


def test_topic_overlap_breaks_single_seed_relevance_ties():
    papers = {
        "S": Paper("S", "Seed", 2020, topics=["Natural Language Processing"]),
        "A": Paper("A", "Related", 2019, topics=["Natural Language Processing"]),
        "B": Paper("B", "Unrelated", 2019, topics=["Protein Structure"]),
    }
    candidates = {
        paper_id: CandidateEvidence(paper_id=paper_id, seed_links={"S"})
        for paper_id in papers
    }
    graph, _ = build_influence_graph(papers)
    score_candidates(papers, graph, candidates, {"S"})
    assert candidates["A"].relevance_score > candidates["B"].relevance_score
