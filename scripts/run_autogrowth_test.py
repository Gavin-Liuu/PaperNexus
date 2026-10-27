from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from papernexus.branching import discover_branches
from papernexus.evaluation import (
    load_json,
    milestone_identifiers,
    paper_identifiers,
)
from papernexus.models import Paper
from papernexus.openalex import OpenAlexClient, OpenAlexConfig, OpenAlexError
from papernexus.ranking import (
    FastEmbedder,
    ranked_ids,
    reciprocal_rank_fusion,
    relation_scores,
    semantic_scores,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test prompt-free atlas branch growth")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--core-result", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--halo-limit", type=int, default=250)
    parser.add_argument("--branches", type=int, default=8)
    parser.add_argument("--search-limit", type=int, default=50)
    parser.add_argument("--queries-per-branch", type=int, default=2)
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    args = parser.parse_args()

    benchmark = load_json(args.benchmark)
    try:
        run_config = next(run for run in benchmark["runs"] if run["id"] == args.run_id)
    except StopIteration as exc:
        raise SystemExit(f"Run {args.run_id!r} is not defined in the benchmark") from exc
    result = load_json(args.core_result)
    client = OpenAlexClient(
        OpenAlexConfig(
            api_key=os.getenv("OPENALEX_API_KEY"),
            mailto=os.getenv("OPENALEX_MAILTO"),
        )
    )
    embedder = FastEmbedder(model_name=args.model)
    core_papers = {
        paper_id: Paper(**paper) for paper_id, paper in result["papers"].items()
    }
    seed_ids = set(result["seeds"])
    halo_papers = dict(core_papers)
    api_errors: list[str] = []

    related_ids: set[str] = set()
    for seed_id in seed_ids:
        try:
            fresh_seed = client.get_work(seed_id)
        except OpenAlexError as exc:
            api_errors.append(f"seed:{seed_id}: {exc}")
            fresh_seed = core_papers[seed_id]
        core_papers[seed_id] = fresh_seed
        halo_papers[seed_id] = fresh_seed
        related_ids.update(fresh_seed.related_works)
        try:
            search_results = client.search_works(fresh_seed.title, limit=100)
        except OpenAlexError as exc:
            api_errors.append(f"seed-title:{seed_id}: {exc}")
            search_results = []
        for paper in search_results:
            halo_papers.setdefault(paper.id, paper)
    try:
        related_papers = client.get_works(sorted(related_ids))
    except OpenAlexError as exc:
        api_errors.append(f"related-works: {exc}")
        related_papers = {}
    for paper_id, paper in related_papers.items():
        halo_papers.setdefault(paper_id, paper)

    halo_semantic, _ = semantic_scores(halo_papers, seed_ids, embedder)
    frontier_ids = sorted(
        (paper_id for paper_id in halo_papers if paper_id not in core_papers),
        key=lambda paper_id: halo_semantic[paper_id],
        reverse=True,
    )[: max(0, args.halo_limit - len(core_papers))]
    filtered_halo = {
        paper_id: halo_papers[paper_id]
        for paper_id in list(core_papers) + frontier_ids
    }

    branches = discover_branches(filtered_halo, set(core_papers), embedder)
    selected_branches = branches[: args.branches]
    expanded_papers = dict(filtered_halo)
    discovered_by_branch: dict[str, set[str]] = {}
    for branch in selected_branches:
        branch_papers: set[str] = set()
        for query in branch.queries[: args.queries_per_branch]:
            try:
                search_results = client.search_works(
                    query, limit=args.search_limit
                )
            except OpenAlexError as exc:
                api_errors.append(f"branch-query:{query}: {exc}")
                search_results = []
            for paper in search_results:
                expanded_papers.setdefault(paper.id, paper)
                branch_papers.add(paper.id)
        discovered_by_branch[branch.id] = branch_papers

    targets = [
        item
        for item in benchmark["milestones"]
        if item["branch"] in run_config["target_branches"]
        and item.get("evaluation_status", "active") == "active"
    ]
    core_identifiers = _paper_identifiers(core_papers)
    held_out = [
        item for item in targets
        if milestone_identifiers(item).isdisjoint(core_identifiers)
    ]
    halo_identifiers = _paper_identifiers(filtered_halo)
    expanded_identifiers = _paper_identifiers(expanded_papers)

    semantic, _ = semantic_scores(expanded_papers, seed_ids, embedder)
    relations = relation_scores(expanded_papers, seed_ids)
    fused = reciprocal_rank_fusion(
        [
            ({paper_id: score["citation"] for paper_id, score in relations.items()}, 1.0),
            (semantic, 0.8),
            ({paper_id: score["coupling"] for paper_id, score in relations.items()}, 0.7),
            ({paper_id: score["cocitation"] for paper_id, score in relations.items()}, 0.6),
        ],
        excluded=seed_ids,
    )
    ranking = ranked_ids(fused)
    top_80_identifiers = _paper_identifiers(
        {paper_id: expanded_papers[paper_id] for paper_id in ranking[:80]}
    )
    branch_visible_ids: list[str] = []
    for branch in selected_branches:
        branch_ids = discovered_by_branch[branch.id]
        branch_visible_ids.extend(
            sorted(
                branch_ids,
                key=lambda paper_id: fused.get(paper_id, 0.0),
                reverse=True,
            )[:10]
        )
    branch_visible_identifiers = _paper_identifiers(
        {paper_id: expanded_papers[paper_id] for paper_id in branch_visible_ids}
    )

    report = {
        "benchmark": benchmark["name"],
        "run_id": args.run_id,
        "method": "seed-title search + related works + semantic/citation communities + generated branch queries",
        "complete": not api_errors,
        "api_errors": api_errors,
        "core_nodes": len(core_papers),
        "raw_halo_nodes": len(halo_papers),
        "filtered_halo_nodes": len(filtered_halo),
        "expanded_nodes": len(expanded_papers),
        "target_milestones": len(targets),
        "held_out_milestones": len(held_out),
        "initial_core_recall": _recall(core_identifiers, targets),
        "automatic_halo_recall": _recall(halo_identifiers, targets),
        "expanded_pool_recall": _recall(expanded_identifiers, targets),
        "held_out_recall_after_expansion": _recall(expanded_identifiers, held_out),
        "final_ranked_recall_at_80": _recall(top_80_identifiers, targets),
        "branch_frontier_recall": _recall(branch_visible_identifiers, targets),
        "missing_after_expansion": _missing_labels(expanded_identifiers, targets),
        "missing_from_top_80": _missing_labels(top_80_identifiers, targets),
        "branches": [
            {
                **branch.to_dict(),
                "representative_titles": [
                    filtered_halo[paper_id].title
                    for paper_id in branch.representative_ids
                ],
            }
            for branch in selected_branches
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.output.with_suffix(".md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    args.snapshot.write_text(
        json.dumps(
            {
                "papers": {
                    paper_id: paper.to_dict()
                    for paper_id, paper in expanded_papers.items()
                },
                "ranking": ranking,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(render_markdown(report))
    return 0


def _paper_identifiers(papers: dict[str, Paper]) -> set[str]:
    return set().union(
        *(paper_identifiers(paper_id, paper.doi) for paper_id, paper in papers.items())
    ) if papers else set()


def _recall(found: set[str], expected: list[dict[str, Any]]) -> float | None:
    if not expected:
        return None
    matches = sum(not milestone_identifiers(item).isdisjoint(found) for item in expected)
    return round(matches / len(expected), 4)


def _missing_labels(found: set[str], expected: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("doi") or item.get("openalex_id") or item["title"])
        for item in expected
        if milestone_identifiers(item).isdisjoint(found)
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Prompt-free atlas growth test",
        "",
        f"- Core nodes: {report['core_nodes']}",
        f"- Raw/filtered halo: {report['raw_halo_nodes']}/{report['filtered_halo_nodes']}",
        f"- Expanded nodes: {report['expanded_nodes']}",
        f"- Held-out milestones: {report['held_out_milestones']}",
        f"- Complete run: {'yes' if report['complete'] else 'no'}",
        f"- Core recall: {_pct(report['initial_core_recall'])}",
        f"- Automatic halo recall: {_pct(report['automatic_halo_recall'])}",
        f"- Expanded pool recall: {_pct(report['expanded_pool_recall'])}",
        f"- Final ranked recall@80: {_pct(report['final_ranked_recall_at_80'])}",
        f"- Branch-frontier recall: {_pct(report['branch_frontier_recall'])}",
        "",
        "## API status",
        "",
        *(
            [f"- {error}" for error in report["api_errors"]]
            if report["api_errors"]
            else ["- No API errors"]
        ),
        "",
        "## Discovered branches",
        "",
    ]
    for branch in report["branches"]:
        lines.extend(
            [
                f"### {branch['label']}",
                "",
                f"- Query: `{branch['query']}`",
                "- Query variants: " + "; ".join(f"`{query}`" for query in branch["queries"]),
                f"- Core/frontier papers: {branch['core_paper_count']}/{branch['frontier_paper_count']}",
                f"- Years: {branch['year_min']}–{branch['year_max']}",
                "- Representatives: " + "; ".join(branch["representative_titles"][:3]),
                "",
            ]
        )
    lines.extend(
        [
            "## Missing",
            "",
            "- After expansion: "
            + (", ".join(report["missing_after_expansion"]) or "none"),
            "- From final top 80: "
            + (", ".join(report["missing_from_top_80"]) or "none"),
            "",
        ]
    )
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


if __name__ == "__main__":
    raise SystemExit(main())
