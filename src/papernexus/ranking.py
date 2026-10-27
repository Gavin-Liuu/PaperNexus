from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Protocol

import networkx as nx
import numpy as np

from .models import Paper


class TextEmbedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


class FastEmbedder:
    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        model_cache: Path = Path(".cache/fastembed"),
        vector_cache: Path = Path(".cache/embeddings"),
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(
                "Install the semantic extra: pip install -e '.[semantic]'"
            ) from exc
        self.model_name = model_name
        self.vector_cache = vector_cache / model_name.replace("/", "--")
        self.vector_cache.mkdir(parents=True, exist_ok=True)
        self.model = TextEmbedding(model_name=model_name, cache_dir=str(model_cache))
        self.cache_hits = 0
        self.cache_misses = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors: list[np.ndarray | None] = [None] * len(texts)
        missing_texts: list[str] = []
        missing_indexes: list[int] = []
        for index, value in enumerate(texts):
            cache_path = self._cache_path(value)
            if cache_path.exists():
                vectors[index] = np.load(cache_path)
                self.cache_hits += 1
            else:
                missing_texts.append(value)
                missing_indexes.append(index)
                self.cache_misses += 1
        if missing_texts:
            generated = list(self.model.embed(missing_texts))
            for index, value, vector in zip(
                missing_indexes, missing_texts, generated, strict=True
            ):
                normalized = _normalize_vector(np.asarray(vector, dtype=np.float32))
                np.save(self._cache_path(value), normalized)
                vectors[index] = normalized
        return np.vstack([vector for vector in vectors if vector is not None])

    def _cache_path(self, text: str) -> Path:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return self.vector_cache / f"{digest}.npy"


def paper_text(paper: Paper) -> str:
    abstract = (paper.abstract or "")[:5000]
    topics = "; ".join(paper.topics)
    return f"Title: {paper.title}\nTopics: {topics}\nAbstract: {abstract}".strip()


def semantic_scores(
    papers: dict[str, Paper], seed_ids: set[str], embedder: TextEmbedder
) -> tuple[dict[str, float], dict[str, np.ndarray]]:
    paper_ids = list(papers)
    matrix = embedder.embed([paper_text(papers[paper_id]) for paper_id in paper_ids])
    vectors = {paper_id: matrix[index] for index, paper_id in enumerate(paper_ids)}
    seed_vectors = [vectors[seed_id] for seed_id in seed_ids]
    scores = {
        paper_id: max(float(np.dot(vector, seed_vector)) for seed_vector in seed_vectors)
        for paper_id, vector in vectors.items()
    }
    return scores, vectors


def relation_scores(
    papers: dict[str, Paper], seed_ids: set[str]
) -> dict[str, dict[str, float]]:
    graph = nx.DiGraph()
    graph.add_nodes_from(papers)
    citers: defaultdict[str, set[str]] = defaultdict(set)
    for citing_id, paper in papers.items():
        for cited_id in paper.referenced_works:
            citers[cited_id].add(citing_id)
            if cited_id in papers:
                graph.add_edge(cited_id, citing_id)

    ancestor_scores: defaultdict[str, float] = defaultdict(float)
    descendant_scores: defaultdict[str, float] = defaultdict(float)
    reverse_graph = graph.reverse(copy=False)
    decay = {1: 1.0, 2: 0.6, 3: 0.3}
    for seed_id in seed_ids:
        for paper_id, distance in nx.single_source_shortest_path_length(
            reverse_graph, seed_id, cutoff=3
        ).items():
            ancestor_scores[paper_id] += decay.get(distance, 0.0) / len(seed_ids)
        for paper_id, distance in nx.single_source_shortest_path_length(
            graph, seed_id, cutoff=3
        ).items():
            descendant_scores[paper_id] += decay.get(distance, 0.0) / len(seed_ids)

    scores: dict[str, dict[str, float]] = {}
    for paper_id, paper in papers.items():
        ancestor = min(1.0, ancestor_scores[paper_id])
        descendant = min(1.0, descendant_scores[paper_id])
        citation = max(ancestor, descendant)
        coupling = max(
            (_normalized_overlap(paper.referenced_works, papers[seed].referenced_works) for seed in seed_ids),
            default=0.0,
        )
        cocitation = max(
            (_normalized_overlap(citers[paper_id], citers[seed]) for seed in seed_ids),
            default=0.0,
        )
        scores[paper_id] = {
            "citation": citation,
            "ancestor": ancestor,
            "descendant": descendant,
            "coupling": coupling,
            "cocitation": cocitation,
        }
    return scores


def reciprocal_rank_fusion(
    score_maps: Iterable[tuple[dict[str, float], float]],
    excluded: set[str] | None = None,
    rank_constant: int = 60,
) -> dict[str, float]:
    excluded = excluded or set()
    fused: defaultdict[str, float] = defaultdict(float)
    for scores, weight in score_maps:
        ranked = sorted(
            (
                (paper_id, score)
                for paper_id, score in scores.items()
                if paper_id not in excluded and score > 0
            ),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        )
        for rank, (paper_id, _) in enumerate(ranked, start=1):
            fused[paper_id] += weight / (rank_constant + rank)
    return dict(fused)


def ranked_ids(scores: dict[str, float], excluded: set[str] | None = None) -> list[str]:
    excluded = excluded or set()
    return [
        paper_id
        for paper_id, _ in sorted(
            ((key, value) for key, value in scores.items() if key not in excluded),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        )
    ]


def directional_quota_rank(
    fused_scores: dict[str, float],
    relations: dict[str, dict[str, float]],
    excluded: set[str] | None = None,
    quota_per_direction: int = 20,
) -> list[str]:
    excluded = excluded or set()
    eligible = set(fused_scores) - excluded

    def direction_rank(name: str) -> list[str]:
        return [
            paper_id
            for paper_id in sorted(
                eligible,
                key=lambda item: (
                    relations[item][name],
                    fused_scores.get(item, 0.0),
                    item,
                ),
                reverse=True,
            )
            if relations[paper_id][name] > 0
        ]

    selected: list[str] = []
    for ranking in (
        direction_rank("ancestor")[:quota_per_direction],
        direction_rank("descendant")[:quota_per_direction],
        ranked_ids(fused_scores, excluded),
    ):
        for paper_id in ranking:
            if paper_id not in selected:
                selected.append(paper_id)
    return selected


def _normalized_overlap(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / math.sqrt(len(left_set) * len(right_set))


def _normalize_vector(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector
