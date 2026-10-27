from __future__ import annotations

import time

from fastapi.testclient import TestClient

from papernexus.models import Paper
from papernexus.web import create_app
from papernexus.web import WebStore


class WebProvider:
    def __init__(self) -> None:
        self.papers = {
            "W1": Paper("W1", "Foundation", 2010, authors=["A. Author"]),
            "W2": Paper(
                "W2",
                "Seed work",
                2017,
                authors=["B. Author"],
                doi="10.1234/seed",
                referenced_works=["W1"],
            ),
            "W3": Paper("W3", "Frontier", 2021, referenced_works=["W2"]),
        }

    def resolve_seed(self, raw_seed: str):
        return self.papers["W2"], [self.papers["W2"]]

    def citing_works(self, work_id: str, limit=25, from_year=None, to_year=None):
        return [self.papers["W3"]]

    def get_works(self, work_ids):
        return {work_id: self.papers[work_id] for work_id in work_ids if work_id in self.papers}

    def search_works(self, query, limit=10, sort=None):
        return []


def _completed_graph(client: TestClient) -> tuple[dict, dict]:
    response = client.post("/api/v1/jobs", json={"seeds": ["seed"]})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    for _ in range(50):
        job_response = client.get(f"/api/v1/jobs/{job_id}")
        job = job_response.json()
        if job["status"] == "completed":
            graph_response = client.get(f"/api/v1/graphs/{job['graph_id']}")
            assert graph_response.status_code == 200
            return job, graph_response.json()
        if job["status"] == "failed":
            raise AssertionError(job)
        time.sleep(0.01)
    raise AssertionError("job did not complete")


def test_web_job_graph_feedback_and_exports(tmp_path):
    app = create_app(tmp_path / "web.sqlite3", client=WebProvider())
    with TestClient(app) as client:
        job, graph = _completed_graph(client)
        graph_id = job["graph_id"]
        assert graph["provenance"]["graph_id"] == graph_id
        paper_id = graph["seeds"][0]

        feedback = client.patch(
            f"/api/v1/graphs/{graph_id}/papers/{paper_id}",
            json={"state": "relevant", "note": "keep"},
        )
        assert feedback.status_code == 200
        refreshed = client.get(f"/api/v1/graphs/{graph_id}").json()
        assert refreshed["feedback"][0]["state"] == "relevant"

        for format_name, content_type in (
            ("json", "application/json"),
            ("csv", "text/csv"),
            ("bibtex", "application/x-bibtex"),
        ):
            exported = client.get(
                f"/api/v1/graphs/{graph_id}/export", params={"format": format_name}
            )
            assert exported.status_code == 200
            assert content_type in exported.headers["content-type"]
            assert exported.text

        searches = client.get("/api/v1/searches")
        assert searches.status_code == 200
        assert searches.json()[0]["graph_id"] == graph_id
        assert searches.json()[0]["paper_count"] == len(graph["papers"])

        deleted = client.delete(f"/api/v1/searches/{graph_id}")
        assert deleted.status_code == 200
        assert client.get(f"/api/v1/graphs/{graph_id}").status_code == 404
        assert client.get("/api/v1/searches").json() == []


def test_web_rejects_invalid_inputs_and_unknown_resources(tmp_path):
    app = create_app(tmp_path / "web.sqlite3", client=WebProvider())
    with TestClient(app) as client:
        assert client.post("/api/v1/jobs", json={"seeds": []}).status_code == 422
        assert client.get("/api/v1/jobs/missing").status_code == 404
        assert client.get("/api/v1/graphs/missing").status_code == 404
        assert client.get("/api/v1/graphs/missing/export").status_code == 404


def test_web_recovers_jobs_left_by_a_previous_worker(tmp_path):
    db_path = tmp_path / "web.sqlite3"
    store = WebStore(db_path)
    job_id = store.create_job(["seed"])
    store.update_job(job_id, status="running", progress="resolving seeds")

    app = create_app(db_path, client=WebProvider())
    with TestClient(app) as client:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        assert job["status"] == "failed"
        assert "restarted" in job["error"]
