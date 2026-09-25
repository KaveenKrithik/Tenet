"""
embeddings.py — local sentence-transformer embedding wrapper.

Uses a singleton pattern so the model is loaded once per process.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model_instance = None
_model_name: Optional[str] = None


def _get_model(model_name: str = "all-MiniLM-L6-v2"):
    """Load (or return cached) the sentence-transformer model."""
    global _model_instance, _model_name
    with _model_lock:
        if _model_instance is None or _model_name != model_name:
            from sentence_transformers import SentenceTransformer
            logger.info("embeddings: loading model %s", model_name)
            _model_instance = SentenceTransformer(model_name)
            _model_name = model_name
    return _model_instance


def embed(text: str, model_name: str = "all-MiniLM-L6-v2") -> list[float]:
    """Return a normalized L2 embedding vector for the given text.

    The vector is always L2-normalised so cosine similarity can be computed
    as a simple dot product.
    """
    model = _get_model(model_name)
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two L2-normalized vectors.

    Since both are normalized, this is equivalent to their dot product.
    """
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    return float(np.dot(a_arr, b_arr))
