# PaperNexus Prototype

This repository currently contains an evidence-aware route-building prototype for the PaperNexus product concept.

## What it does

- Resolves 1–3 DOI, OpenAlex ID, arXiv-like identifier, or title inputs.
- Retrieves direct references and citing works from OpenAlex.
- Builds confirmed citation edges oriented from earlier work to later work.
- Extracts up to three short research routes.
- Produces an explainable priority reading list.
- Exports JSON for a future Web UI and a readable Markdown report.

The prototype does not claim that a citation proves causal influence. Bridge scores are local to the sampled graph.

## Domain-independent retrieval planner

The default pipeline uses a bounded retrieval planner: seed identity resolution,
direct references and citers, short metadata-derived searches, review searches,
then at most two rounds of backward citation expansion. The candidate pool is
kept separate from the displayed graph. Only time-consistent citation edges are
used in routes; text similarity and co-citation are discovery evidence.

Run the frozen cross-domain A/B/C comparison with the same seed and request
budget:

```powershell
$env:OPENALEX_API_KEY = "your-key"
.\.venv\Scripts\python scripts\run_retrieval_ablation.py `
  --benchmark benchmarks\cross-domain-v2.json `
  --output output\cross-domain-v2-retrieval-ablation
```

The report includes candidate-pool recall, Recall@10/20/50/80, route recall,
request counts, elapsed time, and cache metrics. It is a development diagnostic,
not a claim of complete disciplinary history.

## Run

```powershell
$env:PYTHONPATH = "src"
python -m papernexus.cli "10.48550/arXiv.1706.03762" --max-nodes 40 --output output/attention
```

An OpenAlex API key is recommended but not required for a small test:

```powershell
$env:OPENALEX_API_KEY = "your-key"
$env:OPENALEX_MAILTO = "you@example.com"
```

## Test

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev,semantic]"
.\.venv\Scripts\python -m pytest
```

## Local Web Alpha

Install the Python package and frontend dependencies once, then run the two
local processes:

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev,semantic]"
.\.venv\Scripts\python -m uvicorn papernexus.web:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd webapp
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. The backend stores jobs and feedback in
`data/papernexus.sqlite3`; set `OPENALEX_API_KEY` in the backend environment.
The Alpha supports seed submission, route/explore views, evidence inspection,
feedback, reading lists, and JSON/CSV/BibTeX export. Expansion currently starts
a new job and returns its source graph ID; it does not merge graphs yet.

## Pi coding harness

This project is configured for Pi through the root `AGENTS.md`. Start Pi from
the repository root so it loads the project instructions:

```powershell
cd path\to\PaperNexus
pi
```

Pi needs a model-provider login or API key. The OpenAlex key is only for the
PaperNexus backend and cannot authenticate Pi. In Pi, use `/login` or configure
the provider environment variable supported by your chosen model.

## Metalens hybrid-ranking experiment

The optional semantic experiment combines citation direction, local BGE embeddings,
bibliographic coupling, and local co-citation. It uses no paid AI API.

```powershell
.\.venv\Scripts\python scripts\run_hybrid_ablation.py `
  --benchmark benchmarks\metalens-v1.json `
  --run core output\metalens.json `
  --run manufacturing output\metalens-manufacturing.json `
  --run computational output\metalens-computational.json `
  --run wide_field output\metalens-wide-field.json `
  --output output\metalens-hybrid-ablation `
  --candidate-snapshot output\metalens-hybrid-candidates.json
```

## Lazy-growing atlas

Build an atlas from a saved route result and candidate snapshot. Embeddings are
computed once and cached locally; listing, previewing, and activating a branch
make no API calls.

```powershell
.\.venv\Scripts\python scripts\lazy_atlas.py init `
  --core-result output\metalens.json `
  --halo-source output\metalens-autogrowth-snapshot.json `
  --output output\metalens-lazy-atlas.json `
  --halo-limit 250 --branch-limit 12 --query-budget 8

.\.venv\Scripts\python scripts\lazy_atlas.py list `
  --atlas output\metalens-lazy-atlas.json

.\.venv\Scripts\python scripts\lazy_atlas.py preview `
  --atlas output\metalens-lazy-atlas.json `
  --branch branch-182dbb0efd --limit 10

.\.venv\Scripts\python scripts\lazy_atlas.py activate `
  --atlas output\metalens-lazy-atlas.json `
  --branch branch-182dbb0efd --limit 20
```

To build the halo from OpenAlex related works instead of a local snapshot, use
`--fetch-related` in place of `--halo-source`. Remote expansion is explicit and
uses one query by default:

```powershell
.\.venv\Scripts\python scripts\lazy_atlas.py expand `
  --atlas output\metalens-lazy-atlas.json `
  --branch branch-182dbb0efd

.\.venv\Scripts\python scripts\lazy_atlas.py rank `
  --atlas output\metalens-lazy-atlas.json `
  --branch branch-182dbb0efd `
  --coarse-limit 50 --limit 20
```

Rank saved remote candidates with a cheap title/topic pass followed by full-text
reranking of the shortlist:

```powershell
.\.venv\Scripts\python scripts\rank_branch_candidates.py `
  --atlas output\metalens-live-expand-demo.json `
  --branch branch-bc78e53a29 `
  --output output\metalens-branch-filter-demo.json `
  --coarse-limit 50 --limit 15
```

## Outputs

- `*.json`: papers, confirmed edges, candidate roles, routes, reading list, provenance, and warnings.
- `*.md`: compact report for human review.
