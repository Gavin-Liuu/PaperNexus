from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from papernexus.evaluation import (
    load_json,
    milestone_identifiers,
    normalize_doi,
    paper_identifiers,
)
from papernexus.models import Paper
from papernexus.openalex import OpenAlexClient, OpenAlexConfig
from papernexus.ranking import (
    directional_quota_rank,
    FastEmbedder,
    ranked_ids,
    reciprocal_rank_fusion,
    relation_scores,
    semantic_scores,
)


STAGES = (
    "citation",
    "citation+semantic",
    "citation+semantic+coupling",
    "citation+semantic+coupling+cocitation",
    "hybrid+directional_quotas",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run hybrid-ranking ablation")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--run", action="append", nargs=2, metavar=("ID", "JSON"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-snapshot", type=Path, required=True)
    parser.add_argument("--search-limit", type=int, default=50)
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    args = parser.parse_args()

    benchmark = load_json(args.benchmark)
    result_paths = {run_id: Path(path) for run_id, path in args.run}
    client = OpenAlexClient(
        OpenAlexConfig(
            api_key=os.getenv("OPENALEX_API_KEY"),
            mailto=os.getenv("OPENALEX_MAILTO"),
        )
    )
    embedder = FastEmbedder(model_name=args.model)
    milestones = benchmark["milestones"]
    snapshots: dict[str, Any] = {}
    run_reports: list[dict[str, Any]] = []

    for run_config in benchmark["runs"]:
        run_id = run_config["id"]
        if run_id not in result_paths:
            continue
        result = load_json(result_paths[run_id])
        papers = {
            paper_id: Paper(**paper) for paper_id, paper in result["papers"].items()
        }
        for query in run_config["queries"]:
            for paper in client.search_works(query, limit=args.search_limit):
                existing = papers.get(paper.id)
                if existing is None or (not existing.abstract and paper.abstract):
                    papers[paper.id] = paper

        seed_ids = set(result["seeds"])
        seed_identifiers = set().union(
            *(paper_identifiers(seed_id, papers[seed_id].doi) for seed_id in seed_ids)
        )
        targets = [
            item
            for item in milestones
            if item["branch"] in run_config["target_branches"]
            and milestone_identifiers(item).isdisjoint(seed_identifiers)
            and item.get("evaluation_status", "active") == "active"
        ]

        semantic, _ = semantic_scores(papers, seed_ids, embedder)
        relations = relation_scores(papers, seed_ids)
        citation = {paper_id: values["citation"] for paper_id, values in relations.items()}
        coupling = {paper_id: values["coupling"] for paper_id, values in relations.items()}
        cocitation = {paper_id: values["cocitation"] for paper_id, values in relations.items()}
        full_fusion = reciprocal_rank_fusion(
            [
                (citation, 1.0),
                (semantic, 0.8),
                (coupling, 0.7),
                (cocitation, 0.6),
            ],
            excluded=seed_ids,
        )
        rankings = {
            "citation": ranked_ids(
                {paper_id: score for paper_id, score in citation.items() if score > 0},
                seed_ids,
            ),
            "citation+semantic": ranked_ids(
                reciprocal_rank_fusion(
                    [(citation, 1.0), (semantic, 0.8)], excluded=seed_ids
                )
            ),
            "citation+semantic+coupling": ranked_ids(
                reciprocal_rank_fusion(
                    [(citation, 1.0), (semantic, 0.8), (coupling, 0.7)],
                    excluded=seed_ids,
                )
            ),
            "citation+semantic+coupling+cocitation": ranked_ids(
                full_fusion
            ),
            "hybrid+directional_quotas": directional_quota_rank(
                full_fusion, relations, excluded=seed_ids, quota_per_direction=5
            ),
        }
        doi_by_id = {paper_id: normalize_doi(paper.doi) for paper_id, paper in papers.items()}
        identifiers_by_id = {
            paper_id: paper_identifiers(paper_id, paper.doi)
            for paper_id, paper in papers.items()
        }
        corpus_identifiers = set().union(*identifiers_by_id.values()) if identifiers_by_id else set()
        run_report = {
            "run_id": run_id,
            "candidate_count": len(papers) - len(seed_ids),
            "target_count": len(targets),
            "candidate_pool_recall": _milestone_recall(corpus_identifiers, targets),
            "stages": {},
        }
        for stage, ranking in rankings.items():
            run_report["stages"][stage] = {
                f"recall@{cutoff}": _milestone_recall(
                    set().union(
                        *(identifiers_by_id[paper_id] for paper_id in ranking[:cutoff])
                    )
                    if ranking[:cutoff]
                    else set(),
                    targets,
                )
                for cutoff in (10, 20, 50, 80)
            }
            run_report["stages"][stage]["top_10"] = [
                {
                    "paper_id": paper_id,
                    "title": papers[paper_id].title,
                    "doi": doi_by_id[paper_id],
                    "semantic": round(semantic[paper_id], 4),
                    **{name: round(value, 4) for name, value in relations[paper_id].items()},
                }
                for paper_id in ranking[:10]
            ]
            run_report["stages"][stage]["top_20"] = [
                {
                    "paper_id": paper_id,
                    "title": papers[paper_id].title,
                    "doi": doi_by_id[paper_id],
                    "semantic": round(semantic[paper_id], 4),
                    **{name: round(value, 4) for name, value in relations[paper_id].items()},
                }
                for paper_id in ranking[:20]
            ]
        final_identifiers = set().union(
            *(identifiers_by_id[paper_id] for paper_id in rankings[STAGES[-1]][:80])
        ) if rankings[STAGES[-1]][:80] else set()
        run_report["missing_from_final_top_80"] = [
            _milestone_label(item)
            for item in targets
            if milestone_identifiers(item).isdisjoint(final_identifiers)
        ]
        run_reports.append(run_report)
        snapshots[run_id] = {
            "queries": run_config["queries"],
            "seeds": sorted(seed_ids),
            "papers": {paper_id: paper.to_dict() for paper_id, paper in papers.items()},
        }

    summary = _summarize(run_reports)
    report = {
        "benchmark": benchmark["name"],
        "benchmark_version": benchmark["version"],
        "model": args.model,
        "search_limit_per_query": args.search_limit,
        "excluded_milestones": [
            item for item in milestones if item.get("evaluation_status", "active") != "active"
        ],
        "summary": summary,
        "runs": run_reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.output.with_suffix(".md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    args.candidate_snapshot.parent.mkdir(parents=True, exist_ok=True)
    args.candidate_snapshot.write_text(
        json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(render_markdown(report))
    return 0


def _milestone_recall(found: set[str], milestones: list[dict[str, Any]]) -> float | None:
    if not milestones:
        return None
    matches = sum(
        not milestone_identifiers(item).isdisjoint(found) for item in milestones
    )
    return round(matches / len(milestones), 4)


def _milestone_label(milestone: dict[str, Any]) -> str:
    return str(
        milestone.get("doi")
        or milestone.get("openalex_id")
        or milestone.get("title")
    )


def _summarize(run_reports: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for stage in STAGES:
        for cutoff in (10, 20, 50, 80):
            values = [
                report["stages"][stage][f"recall@{cutoff}"]
                for report in run_reports
                if report["stages"][stage][f"recall@{cutoff}"] is not None
            ]
            summary.setdefault(stage, {})[f"macro_recall@{cutoff}"] = round(
                sum(values) / len(values), 4
            )
    return summary


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Hybrid ranking ablation",
        "",
        f"- Embedding model: `{report['model']}`",
        f"- Search candidates per query: {report['search_limit_per_query']}",
        "",
        "## Aggregate recall",
        "",
        "| Stage | Recall@10 | Recall@20 | Recall@50 | Recall@80 |",
        "|---|---:|---:|---:|---:|",
    ]
    for stage in STAGES:
        values = report["summary"][stage]
        lines.append(
            f"| {stage} | {_pct(values['macro_recall@10'])} | "
            f"{_pct(values['macro_recall@20'])} | {_pct(values['macro_recall@50'])} | "
            f"{_pct(values['macro_recall@80'])} |"
        )
    lines.extend(["", "## Runs", ""])
    for run in report["runs"]:
        final = run["stages"][STAGES[-1]]
        lines.extend(
            [
                f"### {run['run_id']}",
                "",
                f"- Candidates: {run['candidate_count']}",
                f"- Candidate-pool recall: {_pct(run['candidate_pool_recall'])}",
                f"- Final recall@20: {_pct(final['recall@20'])}",
                f"- Final recall@80: {_pct(final['recall@80'])}",
                "- Missing at final top 80: "
                + (", ".join(run["missing_from_final_top_80"]) or "none"),
                "",
            ]
        )
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


if __name__ == "__main__":
    raise SystemExit(main())
