from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests

from .models import Paper


OPENALEX_ID_RE = re.compile(r"(?:https?://openalex\.org/)?(W\d+)$", re.IGNORECASE)
DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)", re.IGNORECASE)
ARXIV_RE = re.compile(
    r"(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*)?((?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?)",
    re.IGNORECASE,
)


class OpenAlexError(RuntimeError):
    pass


@dataclass(slots=True)
class OpenAlexConfig:
    api_key: str | None = None
    mailto: str | None = None
    timeout_seconds: float = 20.0
    max_retries: int = 4
    cache_dir: Path | None = Path(".cache/openalex")
    cache_ttl_seconds: int = 7 * 24 * 60 * 60
    min_request_interval_seconds: float = 0.25


class OpenAlexClient:
    base_url = "https://api.openalex.org"

    def __init__(self, config: OpenAlexConfig | None = None) -> None:
        self.config = config or OpenAlexConfig()
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "PaperNexus-prototype/0.1 (research-route prototype)"}
        )
        self._last_request_at = 0.0
        self.metrics = {
            "http_attempts": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    def reset_metrics(self) -> None:
        """Reset request counters before an isolated benchmark run."""
        for key in self.metrics:
            self.metrics[key] = 0

    def metrics_snapshot(self) -> dict[str, int]:
        return dict(self.metrics)

    def resolve_seed(self, raw_seed: str) -> tuple[Paper, list[Paper]]:
        seed = raw_seed.strip()
        openalex_match = OPENALEX_ID_RE.fullmatch(seed)
        if openalex_match:
            paper = self.get_work(openalex_match.group(1).upper())
            return paper, [paper]

        doi_match = DOI_RE.fullmatch(seed.rstrip(". "))
        if doi_match:
            doi = doi_match.group(1).rstrip(". ")
            arxiv_doi = re.fullmatch(r"10\.48550/arxiv\.(.+)", doi, re.IGNORECASE)
            if arxiv_doi:
                return self._resolve_arxiv(arxiv_doi.group(1))
            paper = self.get_work(f"https://doi.org/{doi}")
            return paper, [paper]

        arxiv_match = ARXIV_RE.fullmatch(seed)
        if arxiv_match:
            return self._resolve_arxiv(arxiv_match.group(1))

        candidates = self.search_works(seed, limit=10)
        if not candidates:
            raise OpenAlexError(f"No OpenAlex work matched seed: {seed}")
        return candidates[0], candidates

    def _resolve_arxiv(self, arxiv_id: str) -> tuple[Paper, list[Paper]]:
        canonical_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)
        response = self.session.get(
            "https://export.arxiv.org/api/query",
            params={"id_list": canonical_id, "max_results": 1},
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", namespace)
        if entry is None:
            raise OpenAlexError(f"arXiv did not return metadata for {canonical_id}")
        title = self._clean_xml_text(entry.findtext("atom:title", default="", namespaces=namespace))
        abstract = self._clean_xml_text(
            entry.findtext("atom:summary", default="", namespaces=namespace)
        )
        published = entry.findtext("atom:published", default="", namespaces=namespace)
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            self._clean_xml_text(author.findtext("atom:name", default="", namespaces=namespace))
            for author in entry.findall("atom:author", namespace)
        ]
        candidates = self.search_works(title, limit=20)
        if not candidates:
            raise OpenAlexError(
                f"OpenAlex has no citation record matching arXiv:{canonical_id}"
            )
        candidates = [
            paper
            for paper in candidates
            if self._is_plausible_arxiv_match(paper, title, authors, year)
        ]
        if not candidates:
            raise OpenAlexError(
                f"OpenAlex has no trustworthy title/author/year match for "
                f"arXiv:{canonical_id}"
            )
        candidates.sort(
            key=lambda paper: self._arxiv_match_score(paper, title, authors, year),
            reverse=True,
        )
        scores = [
            self._arxiv_match_score(paper, title, authors, year)
            for paper in candidates
        ]
        selected = candidates[0]
        selected.title = title
        selected.year = year
        selected.authors = authors
        selected.abstract = abstract or selected.abstract
        selected.doi = f"https://doi.org/10.48550/arXiv.{canonical_id}"
        selected.oa_url = f"https://arxiv.org/abs/{canonical_id}"
        selected.source = "openalex+arxiv"
        alternatives = [selected] if self._is_confident_match(scores) else candidates
        return selected, alternatives

    @staticmethod
    def _is_confident_match(scores: list[float]) -> bool:
        if not scores or scores[0] < 0.85:
            return False
        return len(scores) == 1 or scores[0] - scores[1] >= 0.05

    @classmethod
    def _is_plausible_arxiv_match(
        cls,
        paper: Paper,
        title: str,
        authors: list[str],
        year: int | None,
    ) -> bool:
        if cls._normalize_text(paper.title) != cls._normalize_text(title):
            return False
        if year is not None and (
            paper.year is None or abs(paper.year - year) > 1
        ):
            return False
        expected_surnames = cls._author_surnames(authors)
        candidate_surnames = cls._author_surnames(paper.authors)
        if expected_surnames:
            overlap = len(expected_surnames & candidate_surnames) / len(
                expected_surnames
            )
            if overlap < 0.5:
                return False
        return True

    @staticmethod
    def _arxiv_match_score(
        paper: Paper,
        title: str,
        authors: list[str],
        year: int | None,
    ) -> float:
        normalized_title = OpenAlexClient._normalize_text(title)
        candidate_title = OpenAlexClient._normalize_text(paper.title)
        title_score = 1.0 if candidate_title == normalized_title else 0.0
        expected_surnames = OpenAlexClient._author_surnames(authors)
        candidate_surnames = OpenAlexClient._author_surnames(paper.authors)
        author_score = len(expected_surnames & candidate_surnames) / max(
            len(expected_surnames), 1
        )
        year_score = 0.0
        if year is not None and paper.year is not None:
            year_score = max(0.0, 1.0 - abs(year - paper.year) / 5)
        return 0.55 * title_score + 0.35 * author_score + 0.10 * year_score

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())

    @staticmethod
    def _author_surnames(authors: Iterable[str]) -> set[str]:
        surnames: set[str] = set()
        for author in authors:
            normalized = OpenAlexClient._normalize_text(author)
            if normalized:
                surnames.add(normalized.split()[-1])
        return surnames

    @staticmethod
    def _clean_xml_text(value: str) -> str:
        return " ".join(value.split())

    def get_work(self, identifier: str) -> Paper:
        encoded_identifier = quote(identifier, safe="")
        data = self._request_json(f"/works/{encoded_identifier}")
        return self._to_paper(data)

    def search_works(
        self,
        query: str,
        limit: int = 10,
        sort: str | None = None,
    ) -> list[Paper]:
        params = {
            "search": query,
            "per_page": min(max(limit, 1), 100),
            "select": self._select_fields(),
        }
        if sort:
            params["sort"] = sort
        data = self._request_json("/works", params=params)
        return [self._to_paper(item) for item in data.get("results", [])]

    def citing_works(
        self,
        work_id: str,
        limit: int = 25,
        from_year: int | None = None,
        to_year: int | None = None,
    ) -> list[Paper]:
        filters = [f"cites:{work_id}", "is_retracted:false"]
        if from_year is not None:
            filters.append(f"from_publication_date:{from_year}-01-01")
        if to_year is not None:
            filters.append(f"to_publication_date:{to_year}-12-31")
        params = {
            "filter": ",".join(filters),
            "sort": "cited_by_count:desc",
            "per_page": min(max(limit, 1), 100),
            "select": self._select_fields(),
        }
        data = self._request_json("/works", params=params)
        return [self._to_paper(item) for item in data.get("results", [])]

    def get_works(self, work_ids: Iterable[str]) -> dict[str, Paper]:
        ids = list(dict.fromkeys(work_ids))
        results: dict[str, Paper] = {}
        for offset in range(0, len(ids), 100):
            batch = ids[offset : offset + 100]
            params = {
                "filter": "openalex:" + "|".join(batch),
                "per_page": 100,
                "select": self._select_fields(),
            }
            data = self._request_json("/works", params=params)
            for item in data.get("results", []):
                paper = self._to_paper(item)
                results[paper.id] = paper
        return results

    def _request_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        request_params = dict(params or {})
        if self.config.api_key:
            request_params["api_key"] = self.config.api_key
        if self.config.mailto:
            request_params["mailto"] = self.config.mailto

        url = f"{self.base_url}{path}"
        cache_path = self._cache_path(url, request_params)
        if cache_path and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age <= self.config.cache_ttl_seconds:
                try:
                    self.metrics["cache_hits"] += 1
                    return json.loads(cache_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
        self.metrics["cache_misses"] += 1
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < self.config.min_request_interval_seconds:
                    time.sleep(self.config.min_request_interval_seconds - elapsed)
                self.metrics["http_attempts"] += 1
                response = self.session.get(
                    url,
                    params=request_params,
                    timeout=self.config.timeout_seconds,
                )
                self._last_request_at = time.monotonic()
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_seconds = max(
                        float(retry_after or 0),
                        2**attempt,
                    )
                    last_error = OpenAlexError(
                        f"HTTP 429 rate limit after attempt {attempt + 1}"
                    )
                    time.sleep(min(wait_seconds, 30.0))
                    continue
                if response.status_code >= 500:
                    last_error = OpenAlexError(
                        f"HTTP {response.status_code} after attempt {attempt + 1}"
                    )
                    time.sleep(min(2**attempt, 30.0))
                    continue
                response.raise_for_status()
                data = response.json()
                if cache_path:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = cache_path.with_suffix(".tmp")
                    temporary.write_text(
                        json.dumps(data, ensure_ascii=False), encoding="utf-8"
                    )
                    temporary.replace(cache_path)
                return data
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self.config.max_retries:
                    time.sleep(min(2**attempt, 30.0))
        safe_error = self._redact_api_key(str(last_error))
        raise OpenAlexError(f"OpenAlex request failed for {url}: {safe_error}")

    def _cache_path(self, url: str, params: dict[str, Any]) -> Path | None:
        if self.config.cache_dir is None:
            return None
        cache_params = {key: value for key, value in params.items() if key != "api_key"}
        payload = json.dumps(
            {"url": url, "params": cache_params},
            sort_keys=True,
            ensure_ascii=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.config.cache_dir / f"{digest}.json"

    @staticmethod
    def _redact_api_key(value: str) -> str:
        return re.sub(r"([?&]api_key=)[^&\s]+", r"\1REDACTED", value)

    @staticmethod
    def _select_fields() -> str:
        return ",".join(
            [
                "id",
                "display_name",
                "publication_year",
                "authorships",
                "doi",
                "cited_by_count",
                "fwci",
                "citation_normalized_percentile",
                "referenced_works",
                "abstract_inverted_index",
                "topics",
                "is_retracted",
                "best_oa_location",
                "updated_date",
                "related_works",
                "type",
            ]
        )

    @classmethod
    def _to_paper(cls, raw: dict[str, Any]) -> Paper:
        work_id = cls._short_id(raw.get("id"))
        percentile_data = raw.get("citation_normalized_percentile") or {}
        best_oa = raw.get("best_oa_location") or {}
        return Paper(
            id=work_id,
            title=raw.get("display_name") or "Untitled work",
            document_type=raw.get("type"),
            year=raw.get("publication_year"),
            authors=[
                authorship.get("author", {}).get("display_name")
                for authorship in raw.get("authorships") or []
                if authorship.get("author", {}).get("display_name")
            ],
            doi=raw.get("doi"),
            cited_by_count=int(raw.get("cited_by_count") or 0),
            fwci=raw.get("fwci"),
            citation_percentile=percentile_data.get("value"),
            referenced_works=[
                cls._short_id(reference)
                for reference in raw.get("referenced_works") or []
            ],
            abstract=cls.reconstruct_abstract(raw.get("abstract_inverted_index")),
            topics=[
                topic.get("display_name")
                for topic in raw.get("topics") or []
                if topic.get("display_name")
            ],
            is_retracted=bool(raw.get("is_retracted")),
            oa_url=best_oa.get("landing_page_url") or best_oa.get("pdf_url"),
            updated_at=raw.get("updated_date"),
            related_works=[
                cls._short_id(related)
                for related in raw.get("related_works") or []
            ],
        )

    @staticmethod
    def _short_id(value: str | None) -> str:
        if not value:
            return ""
        return value.rsplit("/", 1)[-1]

    @staticmethod
    def reconstruct_abstract(index: dict[str, list[int]] | None) -> str | None:
        if not index:
            return None
        positions: list[tuple[int, str]] = []
        for word, offsets in index.items():
            positions.extend((offset, word) for offset in offsets)
        return " ".join(word for _, word in sorted(positions))
