"""
config.py — loads and validates config.yaml via Pydantic v2.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Sub-config models
# ---------------------------------------------------------------------------

class GraphConfig(BaseModel):
    languages: list[str] = ["python", "javascript", "typescript"]
    max_hops: int = 2
    db_path: str = "data/graph.sqlite"


class CacheConfig(BaseModel):
    embedding_model: str = "all-MiniLM-L6-v2"
    similarity_threshold: float = 0.92
    ttl_hours: int = 168
    db_path: str = "data/cache.sqlite"


class TriageConfig(BaseModel):
    ollama_model: str = "qwen2.5-coder:7b"
    ollama_host: str = "http://localhost:11434"
    max_local_hops: int = 2
    validation_timeout_seconds: int = 10


class TierConfig(BaseModel):
    max_hops: Optional[int] = None
    max_nodes: Optional[int] = None


class RouterTiersConfig(BaseModel):
    cheap: TierConfig = TierConfig(max_hops=2, max_nodes=5)
    mid: TierConfig = TierConfig(max_hops=5, max_nodes=20)
    full: TierConfig = TierConfig(max_hops=None, max_nodes=None)


class RouterConfig(BaseModel):
    tiers: RouterTiersConfig = RouterTiersConfig()
    cost_confirmation_threshold_tokens: int = 20000
    tokens_per_node_estimate: int = 800
    monthly_token_budget: int = 1_000_000  # total budget; 0 = unlimited


class LedgerConfig(BaseModel):
    db_path: str = "data/ledger.sqlite"
    anomaly_multiplier: float = 3.0


class DashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8420


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

class TenetConfig(BaseModel):
    graph: GraphConfig = Field(default_factory=GraphConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    ledger: LedgerConfig = Field(default_factory=LedgerConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)

    @model_validator(mode="after")
    def ensure_data_dirs(self) -> "TenetConfig":
        """Create parent directories for all configured db_path values."""
        for db_path in (self.graph.db_path, self.cache.db_path, self.ledger.db_path):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return self


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
_config_cache: Optional[TenetConfig] = None


def load_config(path: Optional[str | Path] = None) -> TenetConfig:
    """Load config from yaml file (defaults to repo-root config.yaml).

    Results are cached so repeated calls within the same process are free.
    Pass ``path`` explicitly to force a different file (useful in tests).
    """
    global _config_cache

    # Allow tests / CLI to force a fresh load
    if path is not None:
        return _load_from_path(Path(path))

    if _config_cache is None:
        config_path = Path(os.environ.get("TENET_CONFIG", str(_DEFAULT_CONFIG_PATH)))
        _config_cache = _load_from_path(config_path)

    return _config_cache


def _load_from_path(path: Path) -> TenetConfig:
    if path.exists():
        with path.open() as fh:
            raw = yaml.safe_load(fh) or {}
    else:
        raw = {}
    return TenetConfig.model_validate(raw)


def reset_config_cache() -> None:
    """Reset the in-process config cache (useful in tests)."""
    global _config_cache
    _config_cache = None
