from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from papernexus.atlas import (
    LazyAtlas,
    collect_related_halo,
    default_embedder,
    load_halo_papers,
)
from papernexus.openalex import OpenAlexClient, OpenAlexConfig, OpenAlexError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage a lazy-growing PaperNexus atlas")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Build a persistent local candidate halo")
    init.add_argument("--core-result", type=Path, required=True)
    halo_group = init.add_mutually_exclusive_group(required=True)
    halo_group.add_argument("--halo-source", type=Path)
    halo_group.add_argument("--fetch-related", action="store_true")
    init.add_argument("--output", type=Path, required=True)
    init.add_argument("--halo-limit", type=int, default=250)
    init.add_argument("--branch-limit", type=int, default=12)
    init.add_argument("--query-budget", type=int, default=8)
    init.add_argument("--model", default="BAAI/bge-small-en-v1.5")

    list_parser = subparsers.add_parser("list", help="List saved branch proposals")
    list_parser.add_argument("--atlas", type=Path, required=True)

    preview = subparsers.add_parser("preview", help="Preview a branch without API/model calls")
    preview.add_argument("--atlas", type=Path, required=True)
    preview.add_argument("--branch", required=True)
    preview.add_argument("--limit", type=int, default=10)
    preview.add_argument("--json", action="store_true")

    activate = subparsers.add_parser("activate", help="Add local branch candidates to the active view")
    activate.add_argument("--atlas", type=Path, required=True)
    activate.add_argument("--branch", required=True)
    activate.add_argument("--limit", type=int, default=20)

    expand = subparsers.add_parser("expand", help="Use remote search for one saved branch")
    expand.add_argument("--atlas", type=Path, required=True)
    expand.add_argument("--branch", required=True)
    expand.add_argument("--queries", type=int, default=1, choices=(1, 2))
    expand.add_argument("--results-per-query", type=int, default=50)

    rank = subparsers.add_parser("rank", help="Rank saved remote candidates locally")
    rank.add_argument("--atlas", type=Path, required=True)
    rank.add_argument("--branch", required=True)
    rank.add_argument("--coarse-limit", type=int, default=50)
    rank.add_argument("--limit", type=int, default=20)
    rank.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    if args.command == "init":
        core = _load_json(args.core_result)
        halo_stats = None
        if args.halo_source:
            halo = load_halo_papers(_load_json(args.halo_source))
        else:
            client = OpenAlexClient(
                OpenAlexConfig(
                    api_key=os.getenv("OPENALEX_API_KEY"),
                    mailto=os.getenv("OPENALEX_MAILTO"),
                    timeout_seconds=10,
                    max_retries=2,
                )
            )
            try:
                halo, halo_stats = collect_related_halo(core, client)
            except OpenAlexError as exc:
                raise SystemExit(str(exc)) from exc
        embedder = default_embedder(args.model)
        atlas = LazyAtlas.build(
            core,
            halo,
            embedder,
            halo_limit=args.halo_limit,
            branch_limit=args.branch_limit,
            query_budget=args.query_budget,
            embedding_model=args.model,
        )
        _save_atlas(args.output, atlas)
        print(
            f"Saved {args.output} | papers={len(atlas.papers)} "
            f"branches={len(atlas.branches)} "
            f"embedding_cache_hits={atlas.embedding_cache_hits} "
            f"embedding_cache_misses={atlas.embedding_cache_misses}"
        )
        if halo_stats:
            print("Related halo: " + json.dumps(halo_stats, ensure_ascii=False))
        return 0

    atlas_path: Path = args.atlas
    atlas = LazyAtlas.from_dict(_load_json(atlas_path))
    if args.command == "list":
        for branch in atlas.branches:
            print(
                f"{branch.id}\t{branch.label}\t"
                f"local={branch.frontier_paper_count}\t"
                f"years={branch.year_min}-{branch.year_max}"
            )
        print(f"Remote query budget: {atlas.query_budget_remaining}")
        return 0
    if args.command == "preview":
        preview_data = atlas.preview_branch(args.branch, args.limit)
        if args.json:
            print(json.dumps(preview_data, ensure_ascii=False, indent=2))
        else:
            branch = preview_data["branch"]
            print(f"{branch['id']} | {branch['label']}")
            print(
                f"Local candidates: {preview_data['local_candidate_count']} | "
                f"remote query required: {preview_data['remote_query_required']} | "
                f"budget remaining: {preview_data['query_budget_remaining']}"
            )
            for paper in preview_data["papers"]:
                print(f"- {paper['year'] or '?'} | {paper['title']} | {paper['doi'] or paper['id']}")
            if preview_data["remote_papers"]:
                print("Verified remote candidates:")
                for paper in preview_data["remote_papers"]:
                    evidence = paper["evidence"]
                    print(
                        f"- [{evidence['tier']}] {paper['year'] or '?'} | "
                        f"{paper['title']} | {paper['doi'] or paper['id']}"
                    )
        return 0
    if args.command == "activate":
        expansion = atlas.activate_local(args.branch, args.limit)
        _save_atlas(atlas_path, atlas)
        print(
            f"Activated {len(expansion.local_paper_ids)} local papers; "
            f"remote queries used: {atlas.query_budget_used}"
        )
        return 0
    if args.command == "rank":
        embedder = default_embedder(args.model)
        try:
            expansion = atlas.rank_remote(
                args.branch,
                embedder,
                coarse_limit=args.coarse_limit,
                limit=args.limit,
                model_name=args.model,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        _save_atlas(atlas_path, atlas)
        visible = [
            item for item in expansion.remote_ranking
            if item.tier in {"verified", "bridge"}
        ]
        print(
            f"Ranked {len(expansion.remote_ranking)} remote candidates; "
            f"visible={len(visible)} elapsed={expansion.ranking_elapsed_seconds:.3f}s "
            f"cache_hits={expansion.ranking_cache_hits} "
            f"cache_misses={expansion.ranking_cache_misses}"
        )
        return 0
    if args.command == "expand":
        client = OpenAlexClient(
            OpenAlexConfig(
                api_key=os.getenv("OPENALEX_API_KEY"),
                mailto=os.getenv("OPENALEX_MAILTO"),
                timeout_seconds=10,
                max_retries=2,
            )
        )
        try:
            expansion = atlas.expand_remote(
                args.branch,
                client,
                max_queries=args.queries,
                results_per_query=args.results_per_query,
            )
        except (OpenAlexError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from exc
        _save_atlas(atlas_path, atlas)
        print(
            f"Added {len(expansion.remote_paper_ids)} remote papers; "
            f"query budget remaining: {atlas.query_budget_remaining}"
        )
        return 0
    return 2


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_atlas(path: Path, atlas: LazyAtlas) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(atlas.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
