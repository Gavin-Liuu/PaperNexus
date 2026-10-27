from papernexus.evaluation import (
    evaluate_atlas,
    merge_atlas,
    milestone_identifiers,
    normalize_doi,
    normalize_openalex_id,
    paper_identifiers,
)


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1234/ABC.1") == "10.1234/abc.1"
    assert normalize_doi("doi:10.1234/abc.1.") == "10.1234/abc.1"


def test_multi_identifier_matching_accepts_openalex_and_doi_aliases():
    milestone = {
        "doi": "10.1234/published",
        "openalex_id": "https://openalex.org/W123",
        "aliases": ["10.48550/arXiv.1234.5678"],
    }
    identifiers = milestone_identifiers(milestone)
    assert "doi:10.1234/published" in identifiers
    assert "doi:10.48550/arxiv.1234.5678" in identifiers
    assert "openalex:W123" in identifiers
    assert normalize_openalex_id("https://openalex.org/w123/") == "W123"
    assert paper_identifiers("W123", None) & identifiers
    assert paper_identifiers("W999", "https://doi.org/10.48550/arXiv.1234.5678") & identifiers


def test_evaluation_separates_seeded_and_unseeded_recall():
    benchmark = {
        "name": "fixture",
        "version": "1",
        "runs": [{"id": "one", "seeds": ["10.1/seed"]}],
        "milestones": [
            {"doi": "10.1/seed", "branch": "main", "title": "Seed", "year": 2020},
            {"doi": "10.1/found", "branch": "main", "title": "Found", "year": 2019},
            {"doi": "10.1/miss", "branch": "other", "title": "Miss", "year": 2021},
        ],
    }
    result = {
        "papers": {
            "W1": {"doi": "https://doi.org/10.1/seed", "year": 2020},
            "W2": {"doi": "https://doi.org/10.1/found", "year": 2019},
        },
        "edges": [{"source": "W2", "target": "W1", "type": "citation"}],
        "reading_list": [{"paper_id": "W1"}],
        "routes": [{"paper_ids": ["W2", "W1"]}],
    }
    evaluation = evaluate_atlas(benchmark, [("one", result)])
    assert evaluation["milestones"]["corpus_recall"] == 0.6667
    assert evaluation["milestones"]["unseeded_corpus_recall"] == 0.5
    assert evaluation["milestones"]["route_recall"] == 0.6667
    assert evaluation["quality"]["reverse_time_edge_count"] == 0


def test_merge_atlas_tracks_discovery_provenance():
    first = {
        "papers": {"W1": {"title": "Shared"}},
        "edges": [],
        "routes": [],
        "reading_list": [],
    }
    second = {
        "papers": {"W1": {"title": "Shared"}, "W2": {"title": "New"}},
        "edges": [{"source": "W1", "target": "W2", "type": "citation"}],
        "routes": [{"id": "route-1", "paper_ids": ["W1", "W2"]}],
        "reading_list": [],
    }
    atlas = merge_atlas([("first", first), ("second", second)])
    assert atlas["papers"]["W1"]["discovered_in"] == ["first", "second"]
    assert atlas["papers"]["W2"]["discovered_in"] == ["second"]
    assert atlas["routes"][0]["id"] == "second:route-1"
