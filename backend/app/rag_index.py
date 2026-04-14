from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class RagChunk:
    id: str
    doc_id: str
    source_type: str
    source_title: str
    source_url: Optional[str]
    version: str
    fetched_at: str
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "source_type": self.source_type,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "version": self.version,
            "fetched_at": self.fetched_at,
            "text": self.text,
        }


class LocalRagIndex:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.chunks_path = data_dir / "rag_chunks.json"
        self.model_path = data_dir / "rag_tfidf.pkl"
        self.chunks: List[RagChunk] = []
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.matrix = None
        self._load()

    def _load(self) -> None:
        if self.chunks_path.exists():
            raw_chunks = json.loads(self.chunks_path.read_text(encoding="utf-8"))
            self.chunks = [RagChunk(**item) for item in raw_chunks]
        else:
            self.chunks = []

        if self.model_path.exists():
            payload = pickle.loads(self.model_path.read_bytes())
            self.vectorizer = payload.get("vectorizer")
            self.matrix = payload.get("matrix")
        else:
            self.vectorizer = None
            self.matrix = None

    def _save(self) -> None:
        self.chunks_path.write_text(
            json.dumps([chunk.to_dict() for chunk in self.chunks], ensure_ascii=True),
            encoding="utf-8",
        )
        if self.vectorizer is not None and self.matrix is not None:
            self.model_path.write_bytes(
                pickle.dumps({"vectorizer": self.vectorizer, "matrix": self.matrix})
            )

    def _chunk_text(self, text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
        if len(text) <= chunk_size:
            return [text]
        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(0, end - overlap)
        return chunks

    def rebuild(self) -> None:
        if not self.chunks:
            self.vectorizer = None
            self.matrix = None
            self._save()
            return

        texts = [chunk.text for chunk in self.chunks]
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=20000)
        self.matrix = self.vectorizer.fit_transform(texts)
        self._save()

    def upsert_document(
        self,
        *,
        doc_id: str,
        source_type: str,
        source_title: str,
        source_url: Optional[str],
        version: str,
        fetched_at: str,
        text: str,
    ) -> Dict[str, Any]:
        old_count = len(self.chunks)
        self.chunks = [chunk for chunk in self.chunks if chunk.doc_id != doc_id]
        removed = old_count - len(self.chunks)

        chunk_texts = self._chunk_text(text)
        for idx, chunk_text in enumerate(chunk_texts):
            chunk = RagChunk(
                id=f"{doc_id}::chunk::{idx}",
                doc_id=doc_id,
                source_type=source_type,
                source_title=source_title,
                source_url=source_url,
                version=version,
                fetched_at=fetched_at,
                text=chunk_text,
            )
            self.chunks.append(chunk)

        self.rebuild()
        return {
            "doc_id": doc_id,
            "removed_chunks": removed,
            "added_chunks": len(chunk_texts),
            "total_chunks": len(self.chunks),
        }

    def search(self, query: str, top_k: int = 5, source_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not query.strip() or self.vectorizer is None or self.matrix is None or not self.chunks:
            return []

        if source_types:
            allowed = set(source_types)
            candidate_indices = [i for i, chunk in enumerate(self.chunks) if chunk.source_type in allowed]
        else:
            candidate_indices = list(range(len(self.chunks)))

        if not candidate_indices:
            return []

        q_vec = self.vectorizer.transform([query])
        candidate_matrix = self.matrix[candidate_indices]
        scores = cosine_similarity(q_vec, candidate_matrix).flatten()

        ranked = sorted(
            [(idx, float(score)) for idx, score in zip(candidate_indices, scores)],
            key=lambda item: item[1],
            reverse=True,
        )

        results: List[Dict[str, Any]] = []
        for idx, score in ranked[: max(1, top_k)]:
            chunk = self.chunks[idx]
            results.append(
                {
                    "chunk_id": chunk.id,
                    "doc_id": chunk.doc_id,
                    "source_type": chunk.source_type,
                    "source_title": chunk.source_title,
                    "source_url": chunk.source_url,
                    "version": chunk.version,
                    "fetched_at": chunk.fetched_at,
                    "text": chunk.text,
                    "score": score,
                }
            )
        return results

    def status(self) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        for chunk in self.chunks:
            by_type[chunk.source_type] = by_type.get(chunk.source_type, 0) + 1
        return {
            "total_chunks": len(self.chunks),
            "source_type_counts": by_type,
            "is_ready": self.vectorizer is not None and self.matrix is not None,
        }
