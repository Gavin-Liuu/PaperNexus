from papernexus.branching import _community_terms, infer_query_prefix
from papernexus.models import Paper


def test_community_terms_distinguish_branches():
    papers = {
        "A": Paper("A", "Broadband achromatic metalens imaging", 2020),
        "B": Paper("B", "Achromatic broadband focusing", 2021),
        "C": Paper("C", "MEMS tunable metalens", 2020),
        "D": Paper("D", "Electrically tunable focal length", 2021),
    }
    terms = _community_terms([{"A", "B"}, {"C", "D"}], papers)
    assert any("achromatic" in term for term in terms[0])
    assert any("tunable" in term for term in terms[1])


def test_query_prefix_is_inferred_from_core_titles():
    papers = {
        "A": Paper("A", "Metalenses for visible imaging", 2020),
        "B": Paper("B", "Broadband metalens imaging", 2021),
    }
    assert infer_query_prefix(papers, {"A", "B"}) == "metalens"
