import csv
import io
import json
import os
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .openalex import OpenAlexClient, OpenAlexConfig
from .pipeline import ResearchRoutePipeline
from .ranking import FastEmbedder
from .search_planner import HistoryPlannerConfig


class WebStore:
    def __init__(self, path: str | Path = "data/papernexus.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    seeds_json TEXT NOT NULL,
                    progress TEXT NOT NULL,
                    graph_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS graphs (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );
                CREATE TABLE IF NOT EXISTS paper_feedback (
                    graph_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    note TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(graph_id, paper_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, check_same_thread=False)
        db.row_factory = sqlite3.Row
        return db

    def create_job(self, seeds: list[str]) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)",
                (job_id, "queued", json.dumps(seeds), "queued", now, now),
            )
        return job_id

    def update_job(self, job_id: str, **values: Any) -> None:
        values["updated_at"] = datetime.now(UTC).isoformat()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._lock, self._connect() as db:
            db.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                (*values.values(), job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def save_graph(self, job_id: str, result: dict[str, Any]) -> str:
        graph_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO graphs VALUES (?, ?, ?, ?)",
                (graph_id, job_id, json.dumps(result, ensure_ascii=False), now),
            )
        return graph_id

    def get_graph(self, graph_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT result_json FROM graphs WHERE id = ?", (graph_id,)
            ).fetchone()
            feedback = db.execute(
                "SELECT paper_id, state, note, updated_at FROM paper_feedback WHERE graph_id = ?",
                (graph_id,),
            ).fetchall()
        if not row:
            return None
        result = json.loads(row[0])
        # Keep the storage identifier in the API payload so clients can form
        # feedback and export URLs without maintaining a second mapping.
        result.setdefault("provenance", {})["graph_id"] = graph_id
        result["feedback"] = [dict(item) for item in feedback]
        return result

    def list_searches(self) -> list[dict[str, Any]]:
        """Return completed searches without exposing the stored full graph."""
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT g.id AS graph_id, j.id AS job_id, j.seeds_json,
                       g.result_json, g.created_at
                FROM graphs AS g
                JOIN jobs AS j ON j.id = g.job_id
                ORDER BY g.created_at DESC
                """
            ).fetchall()
        searches: list[dict[str, Any]] = []
        for row in rows:
            result = json.loads(row["result_json"])
            papers = result.get("papers", {})
            seed_ids = result.get("seeds", [])
            seed_titles = [
                papers[paper_id].get("title", paper_id)
                for paper_id in seed_ids
                if paper_id in papers
            ]
            searches.append(
                {
                    "graph_id": row["graph_id"],
                    "job_id": row["job_id"],
                    "seeds": json.loads(row["seeds_json"]),
                    "seed_titles": seed_titles,
                    "paper_count": len(papers),
                    "created_at": row["created_at"],
                }
            )
        return searches

    def delete_search(self, graph_id: str) -> bool:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT job_id FROM graphs WHERE id = ?", (graph_id,)
            ).fetchone()
            if not row:
                return False
            db.execute("DELETE FROM paper_feedback WHERE graph_id = ?", (graph_id,))
            db.execute("DELETE FROM graphs WHERE id = ?", (graph_id,))
            db.execute("DELETE FROM jobs WHERE id = ?", (row["job_id"],))
        return True

    def save_feedback(self, graph_id: str, paper_id: str, state: str, note: str | None) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO paper_feedback VALUES (?, ?, ?, ?, ?)",
                (graph_id, paper_id, state, note, now),
            )

    def recover_orphaned_jobs(self) -> int:
        """Mark jobs from a previous process as failed instead of leaving them stuck."""
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                UPDATE jobs
                SET status = 'failed', progress = 'failed',
                    error = 'Worker process restarted before this job completed',
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (now,),
            )
        return cursor.rowcount


def create_app(
    db_path: str | Path = "data/papernexus.sqlite3",
    client: OpenAlexClient | None = None,
):
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import PlainTextResponse, Response
    from pydantic import BaseModel, Field

    app = FastAPI(title="PaperNexus Web Alpha", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    store = WebStore(db_path)
    store.recover_orphaned_jobs()
    provider_config = OpenAlexConfig(
        api_key=os.getenv("OPENALEX_API_KEY"),
        mailto=os.getenv("OPENALEX_MAILTO"),
        timeout_seconds=12.0,
        max_retries=2,
    )
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="papernexus-job")
    semantic_enabled = os.getenv("PAPERNEXUS_ENABLE_SEMANTIC", "1").casefold() not in {
        "0", "false", "no"
    }
    semantic_embedder = None
    semantic_lock = threading.Lock()

    def get_semantic_embedder():
        nonlocal semantic_embedder
        if not semantic_enabled:
            return None
        if semantic_embedder is None:
            with semantic_lock:
                if semantic_embedder is None:
                    try:
                        semantic_embedder = FastEmbedder()
                    except Exception:
                        # The semantic extra is optional; citation retrieval
                        # remains fully usable without the local model.
                        semantic_embedder = False
        return semantic_embedder or None

    class JobRequest(BaseModel):
        seeds: list[str] = Field(min_length=1, max_length=3)
        max_nodes: int | None = Field(default=None, ge=3, le=150)

    class ExpansionRequest(BaseModel):
        paper_id: str | None = None
        max_nodes: int | None = Field(default=None, ge=3, le=150)

    class FeedbackRequest(BaseModel):
        state: str = Field(pattern="^(unread|reading|done|relevant|excluded)$")
        note: str | None = Field(default=None, max_length=1000)

    def start_job(job_id: str, seeds: list[str], max_nodes: int, source_graph: str | None = None) -> None:
        def work() -> None:
            try:
                store.update_job(job_id, status="running", progress="resolving seeds")

                def update_progress(stage: str) -> None:
                    store.update_job(job_id, progress=stage)

                job_provider = client or OpenAlexClient(provider_config)
                result = ResearchRoutePipeline(
                    job_provider, semantic_embedder=get_semantic_embedder()
                ).build(
                    seeds,
                    max_nodes=max_nodes,
                    neighbors_per_seed=20,
                    planner_config=HistoryPlannerConfig(
                        max_http_attempts=30,
                        max_backward_rounds=2,
                        max_seconds=600.0,
                    ),
                    progress_callback=update_progress,
                )
                store.update_job(job_id, progress="saving graph")
                graph_id = store.save_graph(job_id, result.to_dict())
                store.update_job(
                    job_id,
                    status="completed",
                    progress="completed",
                    graph_id=graph_id,
                    error=None,
                )
            except Exception as exc:  # surfaced through job status, never swallowed
                store.update_job(job_id, status="failed", progress="failed", error=str(exc))

        executor.submit(work)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "papernexus-web-alpha"}

    @app.post("/api/v1/jobs", status_code=202)
    def create_job(request: JobRequest) -> dict[str, str]:
        job_id = store.create_job(request.seeds)
        start_job(job_id, request.seeds, request.max_nodes)
        return {"job_id": job_id, "status": "queued"}

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(404, "Unknown job")
        job["seeds"] = json.loads(job.pop("seeds_json"))
        return job

    @app.get("/api/v1/searches")
    def list_searches() -> list[dict[str, Any]]:
        return store.list_searches()

    @app.delete("/api/v1/searches/{graph_id}")
    def delete_search(graph_id: str) -> dict[str, str]:
        if not store.delete_search(graph_id):
            raise HTTPException(404, "Unknown search")
        return {"status": "deleted", "graph_id": graph_id}

    @app.post("/api/v1/graphs/{graph_id}/expand", status_code=202)
    def expand_graph(graph_id: str, request: ExpansionRequest) -> dict[str, str]:
        graph = store.get_graph(graph_id)
        if not graph:
            raise HTTPException(404, "Unknown graph")
        seeds = list(graph.get("seeds", []))
        if request.paper_id and request.paper_id not in seeds:
            seeds = [*seeds, request.paper_id][:3]
        job_id = store.create_job(seeds)
        start_job(job_id, seeds, request.max_nodes, source_graph=graph_id)
        return {"job_id": job_id, "status": "queued", "source_graph_id": graph_id}

    @app.get("/api/v1/graphs/{graph_id}")
    def get_graph(graph_id: str) -> dict[str, Any]:
        graph = store.get_graph(graph_id)
        if not graph:
            raise HTTPException(404, "Unknown graph")
        return graph

    @app.patch("/api/v1/graphs/{graph_id}/papers/{paper_id}")
    @app.patch("/api/v1/projects/{graph_id}/papers/{paper_id}")
    def update_paper(graph_id: str, paper_id: str, request: FeedbackRequest) -> dict[str, str]:
        graph = store.get_graph(graph_id)
        if not graph or paper_id not in graph.get("papers", {}):
            raise HTTPException(404, "Unknown graph or paper")
        store.save_feedback(graph_id, paper_id, request.state, request.note)
        return {"status": "saved", "paper_id": paper_id}

    @app.get("/api/v1/graphs/{graph_id}/export")
    def export_graph(graph_id: str, format: str = Query(default="json")) -> Response:
        graph = store.get_graph(graph_id)
        if not graph:
            raise HTTPException(404, "Unknown graph")
        if format == "json":
            return Response(json.dumps(graph, ensure_ascii=False, indent=2), media_type="application/json")
        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "title", "year", "doi", "cited_by_count"])
            for paper in graph.get("papers", {}).values():
                writer.writerow([paper.get(key, "") for key in ("id", "title", "year", "doi", "cited_by_count")])
            return Response(output.getvalue(), media_type="text/csv")
        if format == "bibtex":
            entries = []
            for paper in graph.get("papers", {}).values():
                key = paper.get("id", "paper")
                authors = " and ".join(paper.get("authors", []))
                entries.append(
                    f"@article{{{key},\n  title = {{{paper.get('title', '')}}},\n  author = {{{authors}}},\n  year = {{{paper.get('year', '')}}},\n  doi = {{{paper.get('doi', '')}}}\n}}"
                )
            return PlainTextResponse("\n\n".join(entries), media_type="application/x-bibtex")
        raise HTTPException(400, "format must be json, csv, or bibtex")

    return app


app = create_app()


def main() -> None:
    """Run the local Web Alpha through Uvicorn."""
    import uvicorn

    uvicorn.run(
        "papernexus.web:app",
        host=os.getenv("PAPERNEXUS_HOST", "127.0.0.1"),
        port=int(os.getenv("PAPERNEXUS_PORT", "8000")),
        reload=False,
    )
