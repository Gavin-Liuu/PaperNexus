from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized.rstrip(". ") or None


def normalize_openalex_id(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().rstrip("/").split("/")[-1].upper()
    return normalized if re.fullmatch(r"W\d+", normalized) else None


def normalized_identifiers(*values: str | None) -> set[str]:
    identifiers: set[str] = set()
    for value in values:
        doi = normalize_doi(value)
        openalex_id = normalize_openalex_id(value)
        if doi and doi.startswith("10."):
            identifiers.add(f"doi:{doi}")
        if openalex_id:
            identifiers.add(f"openalex:{openalex_id}")
    return identifiers


def milestone_identifiers(milestone: dict[str, Any]) -> set[str]:
    values = [
        milestone.get("doi"),
        milestone.get("openalex_id"),
        *milestone.get("aliases", []),
    ]
    return normalized_identifiers(*values)


def paper_identifiers(paper_id: str, doi: str | None) -> set[str]:
    return normalized_identifiers(paper_id, doi)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def merge_atlas(runs: Iterable[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    papers: dict[str, dict[str, Any]] = {}
    discovered_in: defaultdict[str, set[str]] = defaultdict(set)
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    edge_runs: defaultdict[tuple[str, str, str], set[str]] = defaultdict(set)
    routes: list[dict[str, Any]] = []
    reading_lists: dict[str, list[dict[str, Any]]] = {}
    source_runs: list[str] = []

    for run_id, result in runs:
        source_runs.append(run_id)
        for paper_id, paper in result["papers"].items():
            papers.setdefault(paper_id, paper)
            discovered_in[paper_id].add(run_id)
        for edge in result.get("edges", []):
            key = (edge["source"], edge["target"], edge.get("type", "citation"))
            edges.setdefault(key, edge)
            edge_runs[key].add(run_id)
        routes.extend(
            {**route, "source_run": run_id, "id": f"{run_id}:{route['id']}"}
            for route in result.get("routes", [])
        )
        reading_lists[run_id] = result.get("reading_list", [])

    merged_papers = {
        paper_id: {**paper, "discovered_in": sorted(discovered_in[paper_id])}
        for paper_id, paper in papers.items()
    }
    merged_edges = [
        {**edge, "discovered_in": sorted(edge_runs[key])}
        for key, edge in edges.items()
    ]
    return {
        "source_runs": source_runs,
        "papers": merged_papers,
        "edges": merged_edges,
        "routes": routes,
        "reading_lists": reading_lists,
    }


def evaluate_atlas(
    benchmark: dict[str, Any],
    runs: Iterable[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    milestones = {
        normalize_doi(item["doi"]): item for item in benchmark["milestones"]
    }
    seeded_dois = {
        normalize_doi(seed)
        for run in benchmark["runs"]
        for seed in run["seeds"]
    }
    atlas_nodes: dict[str, dict[str, Any]] = {}
    atlas_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    reading_dois: set[str] = set()
    route_dois: set[str] = set()
    growth: list[dict[str, Any]] = []
    doi_to_ids: defaultdict[str, set[str]] = defaultdict(set)

    for run_id, result in runs:
        prior_keys = set(atlas_nodes)
        paper_dois = {
            paper_id: normalize_doi(paper.get("doi"))
            for paper_id, paper in result["papers"].items()
        }
        for paper_id, paper in result["papers"].items():
            doi = paper_dois[paper_id]
            key = f"doi:{doi}" if doi else f"openalex:{paper_id}"
            atlas_nodes.setdefault(key, paper)
            if doi:
                doi_to_ids[doi].add(paper_id)
        for edge in result.get("edges", []):
            edge_key = (edge["source"], edge["target"], edge.get("type", "citation"))
            atlas_edges.setdefault(edge_key, edge)
        for item in result.get("reading_list", []):
            doi = paper_dois.get(item["paper_id"])
            if doi:
                reading_dois.add(doi)
        for route in result.get("routes", []):
            for paper_id in route["paper_ids"]:
                doi = paper_dois.get(paper_id)
                if doi:
                    route_dois.add(doi)

        corpus_dois = {
            normalize_doi(paper.get("doi")) for paper in atlas_nodes.values()
        }
        corpus_dois.discard(None)
        found = set(milestones) & corpus_dois
        growth.append(
            {
                "run_id": run_id,
                "run_nodes": len(result["papers"]),
                "new_nodes": len(set(atlas_nodes) - prior_keys),
                "atlas_nodes": len(atlas_nodes),
                "milestones_found_cumulative": len(found),
                "milestone_recall_cumulative": round(len(found) / len(milestones), 4),
            }
        )

    corpus_dois = {normalize_doi(paper.get("doi")) for paper in atlas_nodes.values()}
    corpus_dois.discard(None)
    all_expected = set(milestones)
    unseeded_expected = all_expected - seeded_dois
    found = all_expected & corpus_dois
    found_unseeded = unseeded_expected & corpus_dois
    branch_metrics: dict[str, dict[str, Any]] = {}
    branches: defaultdict[str, set[str]] = defaultdict(set)
    for doi, item in milestones.items():
        branches[item["branch"]].add(doi)
    for branch, expected in sorted(branches.items()):
        branch_unseeded = expected - seeded_dois
        branch_metrics[branch] = {
            "expected": len(expected),
            "corpus_found": len(expected & corpus_dois),
            "corpus_recall": _ratio(len(expected & corpus_dois), len(expected)),
            "unseeded_expected": len(branch_unseeded),
            "unseeded_found": len(branch_unseeded & corpus_dois),
            "unseeded_recall": _ratio(
                len(branch_unseeded & corpus_dois), len(branch_unseeded)
            ),
        }

    years_by_id: dict[str, int | None] = {}
    for _, result in runs:
        years_by_id.update(
            {paper_id: paper.get("year") for paper_id, paper in result["papers"].items()}
        )
    reverse_time_edges = 0
    for source, target, _ in atlas_edges:
        source_year = years_by_id.get(source)
        target_year = years_by_id.get(target)
        if source_year is not None and target_year is not None and source_year > target_year:
            reverse_time_edges += 1

    duplicate_dois = {
        doi: sorted(ids) for doi, ids in doi_to_ids.items() if len(ids) > 1
    }
    return {
        "benchmark": benchmark["name"],
        "benchmark_version": benchmark["version"],
        "run_count": len(growth),
        "atlas_nodes": len(atlas_nodes),
        "atlas_edges": len(atlas_edges),
        "milestones": {
            "expected": len(all_expected),
            "found_in_corpus": len(found),
            "corpus_recall": _ratio(len(found), len(all_expected)),
            "unseeded_expected": len(unseeded_expected),
            "unseeded_found_in_corpus": len(found_unseeded),
            "unseeded_corpus_recall": _ratio(
                len(found_unseeded), len(unseeded_expected)
            ),
            "found_in_reading_lists": len(all_expected & reading_dois),
            "reading_list_recall": _ratio(
                len(all_expected & reading_dois), len(all_expected)
            ),
            "found_in_routes": len(all_expected & route_dois),
            "route_recall": _ratio(len(all_expected & route_dois), len(all_expected)),
            "missing_from_corpus": [milestones[doi] for doi in sorted(all_expected - found)],
        },
        "branches": branch_metrics,
        "growth": growth,
        "quality": {
            "duplicate_doi_count": len(duplicate_dois),
            "duplicate_dois": duplicate_dois,
            "reverse_time_edge_count": reverse_time_edges,
        },
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def render_evaluation_markdown(evaluation: dict[str, Any]) -> str:
    milestones = evaluation["milestones"]
    lines = [
        "# Metalens living-atlas evaluation",
        "",
        f"- Runs merged: {evaluation['run_count']}",
        f"- Atlas: {evaluation['atlas_nodes']} nodes, {evaluation['atlas_edges']} citation edges",
        f"- Milestone corpus recall: {milestones['found_in_corpus']}/{milestones['expected']} ({_percent(milestones['corpus_recall'])})",
        f"- Unseeded milestone recall: {milestones['unseeded_found_in_corpus']}/{milestones['unseeded_expected']} ({_percent(milestones['unseeded_corpus_recall'])})",
        f"- Reading-list visibility: {milestones['found_in_reading_lists']}/{milestones['expected']} ({_percent(milestones['reading_list_recall'])})",
        f"- Route visibility: {milestones['found_in_routes']}/{milestones['expected']} ({_percent(milestones['route_recall'])})",
        "",
        "## Growth",
        "",
        "| Run | Run nodes | New nodes | Atlas nodes | Cumulative milestone recall |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in evaluation["growth"]:
        lines.append(
            f"| {item['run_id']} | {item['run_nodes']} | {item['new_nodes']} | "
            f"{item['atlas_nodes']} | {_percent(item['milestone_recall_cumulative'])} |"
        )
    lines.extend(
        [
            "",
            "## Branch coverage",
            "",
            "| Branch | Corpus | Unseeded |",
            "|---|---:|---:|",
        ]
    )
    for branch, metrics in evaluation["branches"].items():
        unseeded = (
            _percent(metrics["unseeded_recall"])
            if metrics["unseeded_recall"] is not None
            else "n/a"
        )
        lines.append(
            f"| {branch} | {metrics['corpus_found']}/{metrics['expected']} "
            f"({_percent(metrics['corpus_recall'])}) | "
            f"{metrics['unseeded_found']}/{metrics['unseeded_expected']} ({unseeded}) |"
        )
    lines.extend(["", "## Missing milestones", ""])
    missing = milestones["missing_from_corpus"]
    if missing:
        lines.extend(
            f"- {item['year']} - {item['title']} (`{item['doi']}`)" for item in missing
        )
    else:
        lines.append("- None")
    quality = evaluation["quality"]
    lines.extend(
        [
            "",
            "## Data quality",
            "",
            f"- Duplicate DOI records after merge: {quality['duplicate_doi_count']}",
            f"- Reverse-time citation edges: {quality['reverse_time_edge_count']}",
            "",
        ]
    )
    return "\n".join(lines)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"
