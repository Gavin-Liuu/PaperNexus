from papernexus.models import Paper
from papernexus.openalex import OpenAlexClient, OpenAlexConfig


def test_arxiv_match_prefers_title_and_author_overlap():
    expected_authors = ["Ashish Vaswani", "Noam Shazeer"]
    good = Paper(
        "W1",
        "Attention Is All You Need",
        2025,
        authors=["Ashish Vaswani", "Noam Shazeer"],
    )
    wrong = Paper(
        "W2",
        "Attention Is All You Need",
        2017,
        authors=["Someone Else"],
    )
    good_score = OpenAlexClient._arxiv_match_score(
        good, "Attention Is All You Need", expected_authors, 2017
    )
    wrong_score = OpenAlexClient._arxiv_match_score(
        wrong, "Attention Is All You Need", expected_authors, 2017
    )
    assert good_score > wrong_score


def test_arxiv_match_ignores_author_names_without_letters_or_digits():
    candidate = Paper(
        "W1",
        "Attention Is All You Need",
        2017,
        authors=["---", "Ashish Vaswani"],
    )
    score = OpenAlexClient._arxiv_match_score(
        candidate,
        "Attention Is All You Need",
        ["Ashish Vaswani"],
        2017,
    )
    assert score == 1.0


def test_arxiv_match_confidence_requires_a_clear_high_score():
    assert OpenAlexClient._is_confident_match([0.9, 0.7])
    assert not OpenAlexClient._is_confident_match([0.9, 0.88])
    assert not OpenAlexClient._is_confident_match([0.8])


def test_arxiv_match_rejects_same_title_and_authors_from_wrong_year():
    wrong = Paper(
        "W1",
        "Attention Is All You Need",
        2025,
        authors=["Ashish Vaswani", "Noam Shazeer"],
    )
    assert not OpenAlexClient._is_plausible_arxiv_match(
        wrong,
        "Attention Is All You Need",
        ["Ashish Vaswani", "Noam Shazeer"],
        2017,
    )


def test_arxiv_match_accepts_consistent_metadata():
    correct = Paper(
        "W1",
        "Attention Is All You Need",
        2017,
        authors=["Ashish Vaswani", "Noam Shazeer"],
    )
    assert OpenAlexClient._is_plausible_arxiv_match(
        correct,
        "Attention Is All You Need",
        ["Ashish Vaswani", "Noam Shazeer"],
        2017,
    )


def test_cache_key_does_not_depend_on_api_key(tmp_path):
    client = OpenAlexClient(OpenAlexConfig(cache_dir=tmp_path))
    first = client._cache_path("https://example.test", {"search": "x", "api_key": "one"})
    second = client._cache_path("https://example.test", {"search": "x", "api_key": "two"})
    assert first == second


def test_openalex_errors_redact_api_keys():
    message = "404 for https://api.openalex.org/works?api_key=secret-value&select=id"
    redacted = OpenAlexClient._redact_api_key(message)
    assert "secret-value" not in redacted
    assert "api_key=REDACTED" in redacted


def test_document_type_survives_openalex_and_saved_paper_roundtrip():
    raw = {"id": "https://openalex.org/W1", "display_name": "Literature overview",
           "publication_year": 2024, "type": "review"}
    paper = OpenAlexClient._to_paper(raw)
    assert "type" in OpenAlexClient._select_fields().split(",")
    assert Paper.from_dict(paper.to_dict()).document_type == "review"
    assert Paper.from_dict({"id": "W2", "title": "Old cached paper", "year": 2020}).document_type is None
