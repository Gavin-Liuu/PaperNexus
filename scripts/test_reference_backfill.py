from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from papernexus.evaluation import milestone_identifiers, paper_identifiers
from papernexus.openalex import OpenAlexClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure review-reference backfill recall")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument("--search-limit", type=int, default=50)
    parser.add_argument("--reference-limit", type=int, default=300)
    args = parser.parse_args()

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    run = next(item for item in benchmark["runs"] if item["id"] == args.run_id)
    targets = [
        item
        for item in benchmark["milestones"]
        if item["branch"] in run["target_branches"]
        and item.get("evaluation_status", "active") == "active"
    ]
    client = OpenAlexClient()
    search_results = {
        paper.id: paper
        for query in args.query
        for paper in client.search_works(query, limit=args.search_limit)
    }
    reference_counts = Counter(
        reference_id
        for paper in search_results.values()
        for reference_id in paper.referenced_works
    )
    selected_reference_ids = [
        paper_id
        for paper_id, _ in reference_counts.most_common(args.reference_limit)
    ]
    references = client.get_works(selected_reference_ids)
    papers = {**search_results, **references}
    found = set().union(
        *(paper_identifiers(paper_id, paper.doi) for paper_id, paper in papers.items())
    ) if papers else set()
    hits = [
        item for item in targets
        if not milestone_identifiers(item).isdisjoint(found)
    ]
    print(f"Run: {args.run_id}")
    print(f"Search results: {len(search_results)}")
    print(f"References fetched: {len(references)}")
    print(f"Milestone recall: {len(hits)}/{len(targets)} ({len(hits) / len(targets):.1%})")
    for item in hits:
        print(f"- {item['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
