from __future__ import annotations

import json
import logging
import os
import uuid
from urllib.error import URLError
from urllib.request import urlopen
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import SKLearnVectorStore
from langchain_core.documents import Document
from langchain_openai import AzureOpenAIEmbeddings, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


logger = logging.getLogger("adu_backend")


class LangChainRagIndex:
    def __init__(self, data_dir: Path, index_name: str = "default") -> None:
        self.data_dir = data_dir
        safe_index_name = "".join(ch for ch in index_name if ch.isalnum() or ch in ("-", "_")) or "default"
        if safe_index_name == "default":
            self.persist_path = data_dir / "rag_langchain.pkl"
            self.manifest_path = data_dir / "rag_langchain_chunks.json"
        else:
            self.persist_path = data_dir / f"rag_langchain_{safe_index_name}.pkl"
            self.manifest_path = data_dir / f"rag_langchain_chunks_{safe_index_name}.json"
        self.embedding_batch_size = max(1, int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "16")))
        self.embedding_healthcheck_on_init = os.getenv("RAG_EMBEDDING_HEALTHCHECK_ON_INIT", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.last_error: Optional[str] = None
        self.embedding_provider: str = "none"
        self.embeddings = None
        self.splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=200)
        self.chunks: List[Dict[str, Any]] = self._load_manifest()
        self.vector_store: Optional[SKLearnVectorStore] = None
        try:
            self.embeddings, self.embedding_provider = self._create_embeddings()
            self._load_persisted_store()
        except Exception as exc:
            self.last_error = str(exc)
            self.vector_store = None
            logger.warning("RAG init degraded mode: %s", exc)

    def _load_persisted_store(self) -> None:
        if self.embeddings is None:
            return

        if not self.persist_path.exists():
            return

        try:
            self.vector_store = SKLearnVectorStore(
                embedding=self.embeddings,
                persist_path=str(self.persist_path),
            )
            self.last_error = None
            logger.info("RAG persisted index loaded path=%s", self.persist_path)
        except Exception as exc:
            self.vector_store = None
            self.last_error = str(exc)
            logger.warning("Failed to load persisted RAG index, rebuild may be required: %s", exc)

    def _create_embeddings(self):
        provider_mode = os.getenv("RAG_EMBEDDING_PROVIDER", "ollama").strip().lower()
        if provider_mode == "ollama":
            return self._create_ollama_embeddings(ollama_only=True)

        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        azure_key = os.getenv("AZURE_OPENAI_API_KEY")
        azure_embedding_deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

        if azure_endpoint and azure_key and azure_embedding_deployment:
            try:
                azure_embeddings = AzureOpenAIEmbeddings(
                    azure_endpoint=azure_endpoint,
                    api_key=azure_key,
                    azure_deployment=azure_embedding_deployment,
                    openai_api_version=azure_api_version,
                )
                if self.embedding_healthcheck_on_init:
                    azure_embeddings.embed_query("embedding health check")
                logger.info("RAG embeddings provider=azure-openai deployment=%s", azure_embedding_deployment)
                return azure_embeddings, "azure-openai"
            except Exception as exc:
                logger.warning("Azure embeddings unavailable, falling back. error=%s", exc)

        model = os.getenv("OPENAI_EMBEDDING_MODEL", "qwen-qwen3-embedding-8b-3")
        api_key = os.getenv("OPENAI_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = self._normalize_openai_base_url(
            os.getenv("OPENAI_EMBEDDING_API_BASE_URL") or os.getenv("OPENAI_API_BASE_URL")
        )

        if api_key:
            try:
                openai_embeddings = OpenAIEmbeddings(model=model, api_key=api_key, base_url=base_url)
                if self.embedding_healthcheck_on_init:
                    openai_embeddings.embed_query("embedding health check")
                logger.info("RAG embeddings provider=openai-compatible model=%s", model)
                return openai_embeddings, "openai-compatible"
            except Exception as exc:
                logger.warning("OpenAI embeddings unavailable, falling back to Ollama. error=%s", exc)

        enable_ollama_fallback = os.getenv("RAG_ENABLE_OLLAMA_FALLBACK", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not enable_ollama_fallback:
            raise RuntimeError(
                "No embedding provider available. Azure/OpenAI embeddings failed. "
                "Set RAG_ENABLE_OLLAMA_FALLBACK=true to allow Ollama fallback."
            )

        return self._create_ollama_embeddings(ollama_only=False)

    def _create_ollama_embeddings(self, ollama_only: bool):
        context_prefix = "No embedding provider available. "
        if ollama_only:
            context_prefix = "Ollama-only embedding mode enabled, but "

        ollama_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding:4b")
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        if not self._is_ollama_available(ollama_base_url):
            raise RuntimeError(
                f"{context_prefix}Ollama is not reachable at "
                f"{ollama_base_url}."
            )
        try:
            ollama_embeddings = OllamaEmbeddings(model=ollama_model, base_url=ollama_base_url)
            if self.embedding_healthcheck_on_init:
                ollama_embeddings.embed_query("embedding health check")
            logger.info("RAG embeddings provider=ollama model=%s", ollama_model)
            return ollama_embeddings, "ollama"
        except Exception as exc:
            raise RuntimeError(
                f"{context_prefix}run Ollama with model "
                f"'{ollama_model}' at {ollama_base_url}."
            ) from exc

    def _is_ollama_available(self, base_url: str) -> bool:
        url = f"{base_url.rstrip('/')}/api/tags"
        try:
            with urlopen(url, timeout=1.5) as response:
                return 200 <= response.status < 300
        except (URLError, TimeoutError, ValueError):
            return False

    def _normalize_openai_base_url(self, base_url: Optional[str]) -> Optional[str]:
        if not base_url:
            return None

        normalized = base_url.strip().rstrip("/")
        if "inference.ml.azure.com" in normalized and not normalized.endswith("/v1"):
            normalized = f"{normalized}/v1"
        return f"{normalized}/"

    def _load_manifest(self) -> List[Dict[str, Any]]:
        if not self.manifest_path.exists():
            return []
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_manifest(self) -> None:
        self.manifest_path.write_text(json.dumps(self.chunks, ensure_ascii=True), encoding="utf-8")

    def _rebuild_store(self, save: bool = True) -> None:
        if self.embeddings is None:
            self.vector_store = None
            if save:
                self._save_manifest()
            return

        if not self.chunks:
            self.vector_store = None
            if save:
                self._save_manifest()
            return

        texts = [item["text"] for item in self.chunks]
        metadatas = [item["metadata"] for item in self.chunks]
        try:
            self.vector_store = None
            for start in range(0, len(texts), self.embedding_batch_size):
                end = start + self.embedding_batch_size
                batch_texts = texts[start:end]
                batch_metadatas = metadatas[start:end]
                if self.vector_store is None:
                    self.vector_store = SKLearnVectorStore.from_texts(
                        texts=batch_texts,
                        embedding=self.embeddings,
                        metadatas=batch_metadatas,
                        persist_path=str(self.persist_path),
                    )
                else:
                    self.vector_store.add_texts(batch_texts, metadatas=batch_metadatas)

            if self.vector_store is None:
                self.last_error = "No text chunks available for index build"
                return

            self.vector_store.persist()
            self.last_error = None
        except Exception as exc:
            self.vector_store = None
            self.last_error = str(exc)
            logger.warning("RAG rebuild degraded mode: %s", exc)
        if save:
            self._save_manifest()

    def rebuild_from_manifest(self) -> Dict[str, Any]:
        self._rebuild_store(save=False)
        return self.status()

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
        self.chunks = [item for item in self.chunks if item["metadata"].get("doc_id") != doc_id]
        removed = old_count - len(self.chunks)

        docs = self.splitter.split_documents(
            [
                Document(
                    page_content=text,
                    metadata={
                        "doc_id": doc_id,
                        "source_type": source_type,
                        "source_title": source_title,
                        "source_url": source_url,
                        "version": version,
                        "fetched_at": fetched_at,
                    },
                )
            ]
        )

        for index, doc in enumerate(docs):
            metadata = dict(doc.metadata)
            metadata["chunk_id"] = f"{doc_id}::chunk::{index}::{uuid.uuid4().hex[:8]}"
            self.chunks.append({"text": doc.page_content, "metadata": metadata})

        self._rebuild_store(save=True)
        return {
            "doc_id": doc_id,
            "removed_chunks": removed,
            "added_chunks": len(docs),
            "total_chunks": len(self.chunks),
        }

    def upsert_document_segments(
        self,
        *,
        doc_id: str,
        source_type: str,
        source_title: str,
        source_url: Optional[str],
        version: str,
        fetched_at: str,
        segments: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        old_count = len(self.chunks)
        self.chunks = [item for item in self.chunks if item["metadata"].get("doc_id") != doc_id]
        removed = old_count - len(self.chunks)

        docs: List[Document] = []
        for segment in segments:
            segment_text = str(segment.get("text") or "").strip()
            if not segment_text:
                continue

            metadata = {
                "doc_id": doc_id,
                "source_type": source_type,
                "source_title": source_title,
                "source_url": source_url,
                "version": version,
                "fetched_at": fetched_at,
            }
            if segment.get("page_number") is not None:
                metadata["page_number"] = int(segment["page_number"])

            split_docs = self.splitter.split_documents(
                [
                    Document(
                        page_content=segment_text,
                        metadata=metadata,
                    )
                ]
            )
            docs.extend(split_docs)

        for index, doc in enumerate(docs):
            metadata = dict(doc.metadata)
            metadata["chunk_id"] = f"{doc_id}::chunk::{index}::{uuid.uuid4().hex[:8]}"
            self.chunks.append({"text": doc.page_content, "metadata": metadata})

        self._rebuild_store(save=True)
        return {
            "doc_id": doc_id,
            "removed_chunks": removed,
            "added_chunks": len(docs),
            "total_chunks": len(self.chunks),
        }

    def search(self, query: str, top_k: int = 5, source_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not query.strip() or not self.vector_store:
            return []

        fetch_k = max(top_k * 4, top_k)
        matches = self.vector_store.similarity_search_with_score(query, k=fetch_k)

        allowed = set(source_types or [])
        rows: List[Dict[str, Any]] = []
        for doc, score in matches:
            metadata = dict(doc.metadata)
            source_type = metadata.get("source_type", "unknown")
            if allowed and source_type not in allowed:
                continue
            rows.append(
                {
                    "chunk_id": metadata.get("chunk_id", ""),
                    "doc_id": metadata.get("doc_id", ""),
                    "source_type": source_type,
                    "source_title": metadata.get("source_title", "Unknown"),
                    "source_url": metadata.get("source_url"),
                    "page_number": metadata.get("page_number"),
                    "version": metadata.get("version", "1"),
                    "fetched_at": metadata.get("fetched_at", ""),
                    "text": doc.page_content,
                    "score": float(1 / (1 + max(score, 0))),
                }
            )
            if len(rows) >= top_k:
                break

        return rows

    def status(self) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        for item in self.chunks:
            source_type = item.get("metadata", {}).get("source_type", "unknown")
            by_type[source_type] = by_type.get(source_type, 0) + 1
        return {
            "total_chunks": len(self.chunks),
            "source_type_counts": by_type,
            "is_ready": self.vector_store is not None,
            "embedding_provider": self.embedding_provider,
            "last_error": self.last_error,
        }
