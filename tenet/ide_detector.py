"""
ide_detector.py — Auto-detect active IDE environment, user plan tier, and model quotas.

Quota values are sourced from:
1. Environment variables (TENET_GEMINI_PCT, TENET_CLAUDE_PCT) — set by CI or wrapper scripts
2. A local ~/.tenet/quota_cache.json written by the quota-sync daemon (future)
3. Sane defaults matching the detected account plan tier
"""
from __future__ import annotations

import json
import os
import sys
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any


@dataclass
class ModelQuotaInfo:
    name: str
    remaining_pct: float
    description: str
    refresh_text: str
    status: str  # "normal" | "warning" | "exhausted"


@dataclass
class IDEDetectionResult:
    ide_name: str           # e.g., "Antigravity IDE", "Cursor", "VS Code", "JetBrains"
    plan_name: str          # e.g., "Antigravity Starter Quota", "Cursor Pro"
    plan_subtext: str
    gemini_quota: ModelQuotaInfo
    claude_gpt_quota: ModelQuotaInfo
    is_detected: bool


def _load_quota_cache() -> dict[str, Any]:
    """Load quota percentages from the local cache file if it exists."""
    cache_path = Path.home() / ".tenet" / "quota_cache.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            pass
    return {}


def _pct_to_status(pct: float) -> str:
    if pct <= 0:
        return "exhausted"
    elif pct < 25:
        return "warning"
    return "normal"


def _gemini_description(pct: float, refresh_text: str) -> str:
    if pct <= 0:
        return f"You have hit your weekly Gemini limit. It will fully refresh {refresh_text}."
    elif pct < 25:
        return f"Gemini quota is running low ({pct:.0f}% remaining). Tenet will prefer local Ollama to preserve allowance. Refreshes {refresh_text}."
    return f"Gemini Models are available. {pct:.0f}% of weekly limit remaining. Refreshes {refresh_text}."


def _claude_description(pct: float, refresh_text: str) -> str:
    if pct <= 0:
        return f"You have hit your weekly Claude/GPT limit. It refreshes {refresh_text}. Tenet will route to local Ollama or Gemini in the interim."
    elif pct < 25:
        return f"Claude/GPT quota is low ({pct:.0f}% remaining). Upgrade to a higher plan for more capacity. Refreshes {refresh_text}."
    return f"Claude and GPT models are available. {pct:.0f}% of weekly limit remaining. Refreshes {refresh_text}."


def detect_ide_and_plan(config_override: Optional[dict[str, Any]] = None) -> IDEDetectionResult:
    """Detect the host IDE environment, user account plan, and model rate limit quotas."""
    config_override = config_override or {}

    # Check environment & filesystem indicators
    env_keys = os.environ
    home = Path.home()

    is_antigravity = (
        "ANTIGRAVITY_IDE" in env_keys
        or (home / ".gemini" / "antigravity-ide").exists()
        or any("antigravity" in p.lower() for p in [sys.prefix, os.getcwd()])
    )

    is_cursor = (
        "CURSOR_TRACE" in env_keys
        or (home / ".cursor").exists()
    )

    is_vscode = (
        "VSCODE_PID" in env_keys
        or "VSCODE_IPC_HOOK" in env_keys
    )

    is_jetbrains = (
        "IDEA_INITIAL_DIRECTORY" in env_keys
        or "JETBRAINS_CLIENT" in env_keys
    )

    # Resolve IDE Name
    if is_antigravity:
        detected_ide = "Antigravity IDE"
        default_plan = "Antigravity Starter Quota"
        plan_subtext = "Local-first token efficiency layer. Tenet is actively compressing your context."
    elif is_cursor:
        detected_ide = "Cursor"
        default_plan = "Cursor Starter Quota"
        plan_subtext = "Standard usage tier. Upgrade for unlimited fast queries."
    elif is_vscode:
        detected_ide = "VS Code"
        default_plan = "VS Code Extension Quota"
        plan_subtext = "Community plan tier with standard model access."
    elif is_jetbrains:
        detected_ide = "JetBrains IDE"
        default_plan = "JetBrains AI Assistant"
        plan_subtext = "Standard IDE subscription tier."
    else:
        detected_ide = "CLI / Terminal"
        default_plan = "Local Developer Tier"
        plan_subtext = "Running standalone local pipeline."

    # Allow explicit config overrides
    plan_name = config_override.get("account_plan")
    if not plan_name or plan_name == "auto":
        plan_name = default_plan

    ide_name = config_override.get("ide_provider")
    if not ide_name or ide_name == "auto":
        ide_name = detected_ide

    # Load live quota values from env vars or cache file
    quota_cache = _load_quota_cache()
    refresh_text = quota_cache.get("refresh_text", "weekly")

    gemini_pct = float(
        env_keys.get("TENET_GEMINI_PCT")
        or quota_cache.get("gemini_pct")
        or 100.0
    )
    claude_pct = float(
        env_keys.get("TENET_CLAUDE_PCT")
        or quota_cache.get("claude_pct")
        or 100.0
    )

    gemini_quota = ModelQuotaInfo(
        name="Gemini Models",
        remaining_pct=round(gemini_pct, 1),
        description=_gemini_description(gemini_pct, refresh_text),
        refresh_text=f"Refreshes {refresh_text}",
        status=_pct_to_status(gemini_pct),
    )

    claude_gpt_quota = ModelQuotaInfo(
        name="Claude and GPT models",
        remaining_pct=round(claude_pct, 1),
        description=_claude_description(claude_pct, refresh_text),
        refresh_text=f"Refreshes {refresh_text}",
        status=_pct_to_status(claude_pct),
    )

    return IDEDetectionResult(
        ide_name=ide_name,
        plan_name=plan_name,
        plan_subtext=plan_subtext,
        gemini_quota=gemini_quota,
        claude_gpt_quota=claude_gpt_quota,
        is_detected=True,
    )
