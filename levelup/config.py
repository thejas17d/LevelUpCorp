"""Loads config.yaml (user settings) and .env (secrets).

Everything the user is expected to change lives in config.yaml. Secrets (API keys,
email app password) live in .env, which is git-ignored.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines) so we don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # Frequently used settings, with safe defaults
    @property
    def min_lpa(self) -> float:
        return float(self.get("search.min_salary_lpa", 8))

    @property
    def dry_run(self) -> bool:
        # Safety default: never submit unless the user explicitly turns this off.
        return bool(self.get("apply.dry_run", True))

    @property
    def daily_cap(self) -> int:
        return int(self.get("apply.max_applications_per_day", 20))

    @property
    def min_score(self) -> int:
        return int(self.get("match.min_score", 70))


def load_config(path: str | os.PathLike | None = None) -> Config:
    _load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    if not cfg_path.exists():
        example = ROOT / "config.example.yaml"
        raise SystemExit(
            f"config.yaml not found at {cfg_path}.\n"
            f"Copy {example.name} to config.yaml and edit it (see HANDOFF.md, step 3)."
        )
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    DATA_DIR.mkdir(exist_ok=True)
    return Config(raw=raw)
