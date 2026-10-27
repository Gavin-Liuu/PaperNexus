from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from papernexus.atlas import LazyAtlas, default_embedder
from papernexus.filtering import rank_candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Two-stage ranking for saved remote branch candidates"
    )
    parser.add_argument("--atlas", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coarse-limit", type=int, default=50)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    raw = _load_json(args.atlas)
    atlas = LazyAtlas.from_dict(raw)
    branch = atlas._branch(args.branch)
    expansion = atlas.expansions.get(args.branch)
    if not expansion or not expansion.remote_paper_ids:
        raise SystemExit(f"Branch has no saved remote candidates: {args.branch}")

    embedder = default_embedder(args.model)
    started = time.perf_counter()
    ranking = rank_candidates(
        atlas.papers,
        expansion.remote_paper_ids,
        branch.query,
        embedder,
        anchor_ids=set(branch.paper_ids),
        coarse_limit=args.coarse_limit,
        limit=args.limit,
    )
    elapsed = time.perf_counter() - started
    output = {
        "atlas": str(args.atlas),
        "branch": branch.to_dict(),
        "remote_candidate_count": len(expansion.remote_paper_ids),
        "ranked_count": len(ranking),
        "elapsed_seconds": round(elapsed, 3),
        "embedding_cache_hits": embedder.cache_hits,
        "embedding_cache_misses": embedder.cache_misses,
        "ranking": [
            {
                **item.to_dict(),
                "paper": atlas.papers[item.paper_id].to_dict(),
            }
            for item in ranking
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Saved {args.output} | candidates={len(expansion.remote_paper_ids)} "
        f"ranked={len(ranking)} elapsed={elapsed:.3f}s "
        f"cache_hits={embedder.cache_hits} cache_misses={embedder.cache_misses}"
    )
    for item in ranking[:10]:
        paper = atlas.papers[item.paper_id]
        print(f"{item.tier}\t{item.final_score:.3f}\t{paper.year or '?'}\t{paper.title}")
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
