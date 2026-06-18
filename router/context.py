"""Core data structures for the delegation router (HERMES-ROUTER-001, Phase 0).

Inert: nothing in the live gateway imports this yet.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Tier(str, Enum):
    LOCAL = "hermes"   # Qwen, free, T0
    CODEX = "codex"    # flat OAuth, auto, T1
    CLAUDE = "claude"  # metered credit, gated, T2


@dataclass
class SelfGrade:
    confidence: float                       # 0.0 - 1.0
    uncertainties: list[str] = field(default_factory=list)
    checks_run: list[dict] = field(default_factory=list)   # [{name, passed}]


@dataclass
class RoutingContext:
    task_type: str
    task_text: str
    self_grade: Optional[SelfGrade] = None
    attempt_n: int = 0
    consecutive_failures: int = 0
    high_stakes: bool = False
    day_spend_usd: float = 0.0
    est_cost_usd: float = 0.0


@dataclass
class RouteDecision:
    tier: Tier
    model: str
    reason: list[str]                       # mandatory — the confidence-inducing payload
    confidence: float = 0.0
    requires_approval: bool = False


@dataclass
class Verdict:
    quality_score: float                    # 0.0 - 5.0
    won: bool
    method: str                             # "deterministic" | "judge" | "human"
    detail: str = ""
