# PaperNexus Pi Harness

This repository is developed with Pi (`@earendil-works/pi-coding-agent`). Use
the project root as the working directory so Pi loads this file.

## Project Rules

- Keep the Python retrieval core and the React Web Alpha as separate layers.
- Do not write API keys or other credentials into source files, fixtures, logs,
  or committed configuration.
- Citation edges are the only evidence allowed in research routes. Semantic,
  co-citation, and shared-reference signals are discovery evidence.
- Preserve the bounded retrieval budgets and provenance fields when changing the
  planner or pipeline.
- Prefer focused tests for behavior changes. Run both Python and frontend checks
  before reporting a change complete.

## Common Commands

```powershell
\.venv\Scripts\python.exe -m pytest -q
cd webapp; npm run build
```

Run the local Alpha in two terminals:

```powershell
\.venv\Scripts\python.exe -m uvicorn papernexus.web:app --host 127.0.0.1 --port 8000
cd webapp; npm run dev -- --host 127.0.0.1 --port 5173
```

The OpenAlex key belongs only in the backend process environment as
`OPENALEX_API_KEY`.

## Evaluation

The frozen A/B/C retrieval comparison is:

```powershell
\.venv\Scripts\python.exe scripts\run_retrieval_ablation.py `
  --benchmark benchmarks\cross-domain-v2.json `
  --output output\cross-domain-v2-retrieval-ablation
```

