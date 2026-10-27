from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .openalex import OpenAlexClient, OpenAlexConfig
from .pipeline import ResearchRoutePipeline
from .report import render_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="papernexus",
        description="Build an evidence-aware research route from 1-3 seed papers.",
    )
    parser.add_argument("seeds", nargs="+", help="DOI, OpenAlex ID, arXiv ID, or title")
    parser.add_argument("--max-nodes", type=int, default=50)
    parser.add_argument("--neighbors-per-seed", type=int, default=15)
    parser.add_argument("--max-routes", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("output/research-route"))
    parser.add_argument("--mailto", default=os.getenv("OPENALEX_MAILTO"))
    parser.add_argument("--api-key", default=os.getenv("OPENALEX_API_KEY"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= len(args.seeds) <= 3:
        raise SystemExit("Provide between 1 and 3 seeds")
    client = OpenAlexClient(
        OpenAlexConfig(api_key=args.api_key, mailto=args.mailto)
    )
    result = ResearchRoutePipeline(client).build(
        args.seeds,
        max_nodes=args.max_nodes,
        neighbors_per_seed=args.neighbors_per_seed,
        max_routes=args.max_routes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.output.with_suffix(".json")
    markdown_path = args.output.with_suffix(".md")
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    print(
        f"Seeds: {len(result.seeds)} | Papers: {len(result.papers)} | "
        f"Routes: {len(result.routes)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

