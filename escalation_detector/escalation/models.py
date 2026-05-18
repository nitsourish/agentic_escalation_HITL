from dataclasses import dataclass
from typing import Literal


@dataclass
class Message:
    role: Literal["user", "bot"]
    message: str


@dataclass
class EscalationDecision:
    escalate: bool
    tier: Literal["rules", "llm"]
    reason: str
    confidence: float = 1.0
