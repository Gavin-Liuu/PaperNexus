from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from papernexus.evaluation import milestone_identifiers, paper_identifiers
from papernexus.openalex import OpenAlexClient, OpenAlexConfig
from papernexus.pipeline import ResearchRoutePipeline
from papernexus.search_planner import HistoryPlannerConfig


VARIANTS = {
    "A_direct": {"max_text_queries": 0, "max_backward_rounds": 0},
    "B_text": {"max_text_queries": 6, "max_backward_rounds": 0},
    "C_backtracking": {"max_text_queries": 6, "max_backward_rounds": 2},
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fair A/B/C retrieval-planner ablation")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--run", action="append", nargs=2, metavar=("ID", "JSON"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-nodes", type=int, default=80)
    parser.add_argument("--neighbors-per-seed", type=int, default=20)
    parser.add_argument("--max-http-attempts", type=int, default=30)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    requested = {run_id: Path(path) for run_id, path in (args.run or [])}
    client = OpenAlexClient(
        OpenAlexConfig(
            api_key=os.getenv("OPENALEX_API_KEY"),
            mailto=os.getenv("OPENALEX_MAILTO"),
        )
    )
    all_reports: list[dict[str, Any]] = []
    for run in benchmark["runs"]:
        run_id = run["id"]
        for variant, overrides in VARIANTS.items():
            client.reset_metrics()
            config = HistoryPlannerConfig(
                max_http_attempts=args.max_http_attempts,
                max_candidate_pool=500,
                max_display_nodes=args.max_nodes,
                citing_limit=args.neighbors_per_seed,
                **overrides,
            )
            started = time.perf_counter()
            result = ResearchRoutePipeline(client).build(
                run["seeds"],
                max_nodes=args.max_nodes,
                neighbors_per_seed=args.neighbors_per_seed,
                planner_config=config,
            )
            elapsed = time.perf_counter() - started
            active_targets = [
                item
                for item in benchmark["milestones"]
                if item["branch"] in run["target_branches"]
                and item.get("status", "active") == "active"
            ]
            result_ids = set().union(
                *(paper_identifiers(paper_id, paper.doi) for paper_id, paper in result.papers.items())
            ) if result.papers else set()
            route_ids = {
                paper_id
                for route in result.routes
                for paper_id in route.paper_ids
                if paper_id in result.papers
            }
            route_identifiers = set().union(
                *(paper_identifiers(paper_id, result.papers[paper_id].doi) for paper_id in route_ids)
            ) if route_ids else set()
            reading_ids = {
                item.paper_id for item in result.reading_list if item.paper_id in result.papers
            }
            reading_identifiers = set().union(
                *(paper_identifiers(paper_id, result.papers[paper_id].doi) for paper_id in reading_ids)
            ) if reading_ids else set()
            retrieval = result.provenance["retrieval"]
            ranked_ids = _ranked_paper_ids(result)
            ranked_identifiers = [
                paper_identifiers(paper_id, result.papers[paper_id].doi)
                for paper_id in ranked_ids
            ]
            metrics = client.metrics_snapshot()
            cache_total = metrics["cache_hits"] + metrics["cache_misses"]
            report = {
                "run_id": run_id,
                "variant": variant,
                "candidate_count": len(result.papers),
                "candidate_pool_count": retrieval["stats"]["raw_retrieved"],
                "raw_retrieved": retrieval["stats"]["raw_retrieved"],
                "identity_resolved": retrieval["stats"]["resolved"],
                "deduplicated": retrieval["stats"]["deduplicated"],
                "selected_candidate_count": len(result.papers),
                "candidate_pool_recall": _recall(result_ids, active_targets),
                "recall_at": {
                    str(cutoff): _recall_at_k(ranked_identifiers, cutoff, active_targets)
                    for cutoff in (10, 20, 50, 80)
                },
                "route_recall": _recall(route_identifiers, active_targets),
                "reading_list_recall": _recall(reading_identifiers, active_targets),
                "route_count": len(result.routes),
                "route_citation_edge_ratio": _route_edge_ratio(result),
                "request_attempts": retrieval["stats"]["request_attempts"],
                "http_attempts": metrics["http_attempts"],
                "cache_hits": metrics["cache_hits"],
                "cache_hit_rate": round(metrics["cache_hits"] / cache_total, 4) if cache_total else None,
                "text_queries": retrieval["stats"]["text_queries"],
                "elapsed_seconds": round(elapsed, 3),
                "warnings": result.warnings,
                "missing_from_candidate_pool": _missing(result_ids, active_targets),
            }
            all_reports.append(report)

    output = {
        "benchmark": benchmark["name"],
        "benchmark_version": benchmark["version"],
        "protocol": {
            "same_seed_inputs": True,
            "same_max_nodes": args.max_nodes,
            "same_neighbors_per_seed": args.neighbors_per_seed,
            "same_http_budget": args.max_http_attempts,
            "variants": VARIANTS,
            "manual_benchmark_queries_added": False,
        },
        "runs": all_reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.output.with_suffix(".md").write_text(render_markdown(output), encoding="utf-8")
    print(render_markdown(output))
    return 0


def _recall(found: set[str], milestones: list[dict[str, Any]]) -> float | None:
    if not milestones:
        return None
    return round(
        sum(not milestone_identifiers(item).isdisjoint(found) for item in milestones)
        / len(milestones),
        4,
    )


def _missing(found: set[str], milestones: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("doi") or item.get("openalex_id") or item.get("title"))
        for item in milestones
        if milestone_identifiers(item).isdisjoint(found)
    ]


def _ranked_paper_ids(result: Any) -> list[str]:
    """Return the selected candidate pool in a deterministic score order."""
    return sorted(
        result.papers,
        key=lambda paper_id: (
            result.candidates[paper_id].route_score,
            result.candidates[paper_id].relevance_score,
            result.papers[paper_id].cited_by_count,
            paper_id,
        ),
        reverse=True,
    )


def _recall_at_k(
    ranked_identifiers: list[set[str]],
    cutoff: int,
    milestones: list[dict[str, Any]],
) -> float | None:
    if not milestones:
        return None
    found = set().union(*ranked_identifiers[:cutoff]) if ranked_identifiers else set()
    return _recall(found, milestones)


def _route_edge_ratio(result: Any) -> float:
    route_edges = sum(max(0, len(route.paper_ids) - 1) for route in result.routes)
    if not route_edges:
        return 0.0
    confirmed = sum(
        1
        for route in result.routes
        for left, right in zip(route.paper_ids, route.paper_ids[1:])
        if any(edge["source"] == left and edge["target"] == right for edge in result.edges)
    )
    return round(confirmed / route_edges, 4)


def render_markdown(output: dict[str, Any]) -> str:
    lines = [
        "# Retrieval planner ablation",
        "",
        "| Run | Variant | Pool recall | R@10 | R@20 | R@50 | R@80 | Route recall | Requests | Seconds |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for report in output["runs"]:
        def pct(value: float | None) -> str:
            return "n/a" if value is None else f"{value * 100:.1f}%"
        recall_at = report["recall_at"]
        lines.append(
            f"| {report['run_id']} | {report['variant']} | {pct(report['candidate_pool_recall'])} | "
            f"{pct(recall_at['10'])} | {pct(recall_at['20'])} | {pct(recall_at['50'])} | "
            f"{pct(recall_at['80'])} | {pct(report['route_recall'])} | "
            f"{report['request_attempts']} | {report['elapsed_seconds']:.1f} |"
        )
    lines.extend(["", "Manual benchmark queries added: no", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
