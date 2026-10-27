from __future__ import annotations

import argparse
import json
from pathlib import Path

from papernexus.evaluation import (
    evaluate_atlas,
    load_json,
    merge_atlas,
    render_evaluation_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate merged PaperNexus result files")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--run", action="append", nargs=2, metavar=("ID", "JSON"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--atlas-output", type=Path)
    args = parser.parse_args()

    benchmark = load_json(args.benchmark)
    runs = [(run_id, load_json(Path(path))) for run_id, path in args.run]
    evaluation = evaluate_atlas(benchmark, runs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.output.with_suffix(".md").write_text(
        render_evaluation_markdown(evaluation), encoding="utf-8"
    )
    if args.atlas_output:
        args.atlas_output.parent.mkdir(parents=True, exist_ok=True)
        args.atlas_output.write_text(
            json.dumps(merge_atlas(runs), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(render_evaluation_markdown(evaluation))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
