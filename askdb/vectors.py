"""Small ChromaDB helper shared by the schema retriever and the few-shot picker.

Each collection stores a hash of the documents it was built from. If the source file
(schema_docs.yaml or fewshot_bank.jsonl) changes, the hash changes and the collection is
rebuilt, so retrieval never runs on a stale index.
"""
import hashlib
import json
from functools import lru_cache

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from .config import settings


@lru_cache
def _client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=settings.chroma_dir)


@lru_cache
def _embedder() -> SentenceTransformerEmbeddingFunction:
    # Normalized vectors: the default L2 distance then ranks exactly like cosine similarity.
    return SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model,
                                                normalize_embeddings=True)


def get_collection(name: str, documents: dict[str, str]) -> chromadb.Collection:
    """Return collection `name` holding exactly `documents` ({id: text}), rebuilding if needed."""
    digest = hashlib.sha256(json.dumps(documents, sort_keys=True).encode()).hexdigest()
    client = _client()
    existing = {c.name for c in client.list_collections()}
    if name in existing:
        collection = client.get_collection(name, embedding_function=_embedder())
        if (collection.metadata or {}).get("source_hash") == digest:
            return collection
        client.delete_collection(name)
    collection = client.create_collection(name, embedding_function=_embedder(),
                                          metadata={"source_hash": digest})
    collection.add(ids=list(documents), documents=list(documents.values()))
    return collection


def nearest(name: str, documents: dict[str, str], query: str, k: int) -> list[str]:
    """Ids of the k documents closest to the query, best first."""
    collection = get_collection(name, documents)
    result = collection.query(query_texts=[query], n_results=min(k, len(documents)))
    return result["ids"][0]
