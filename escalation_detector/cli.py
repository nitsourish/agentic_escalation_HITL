#!/usr/bin/env python3
"""
Command-line interface for the agentic escalation detector.

Two modes:
  Interactive  — type messages turn-by-turn; the detector evaluates after each
                 user turn and prints the escalation status.
  Replay       — load a labeled conversation from the dataset and step through
                 it turn-by-turn to observe when the detector would have fired.

Usage:
  python cli.py                          # interactive session
  python cli.py --replay c001            # replay conversation c001
  python cli.py --replay c001 --llm-only # skip Tier 1 rules
  python cli.py --no-nli                 # regex fallback instead of NLI
  python cli.py --data path/to/data.json # custom dataset path
"""

import argparse
import json
import sys
from pathlib import Path

from escalation import EscalationDetector, Message
from escalation.config import load_llm_config
from escalation.llm_classifier import create_classifier
from escalation.rules import load_intent_classifier, RuleEngine

_DEFAULT_DATA = Path(__file__).parent / "data" / "escalation_dataset.json"
_BORDER = "─" * 60


def _load_conversation(data_path: Path, conversation_id: str) -> list[Message]:
    with open(data_path, encoding="utf-8") as f:
        dataset = json.load(f)
    for conv in dataset:
        if conv["conversation_id"] == conversation_id:
            return [Message(role=m["role"], message=m["message"]) for m in conv["conversation_history"]]
    ids = [c["conversation_id"] for c in dataset]
    raise ValueError(f"Conversation '{conversation_id}' not found. Available: {ids}")


def _print_decision(decision) -> None:
    if decision.escalate:
        print(f"\n🚨  ESCALATE  — {decision.reason}  [tier={decision.tier}, conf={decision.confidence:.2f}]")
    else:
        print(f"\n✅  CONTINUE  — {decision.reason}  [tier={decision.tier}, conf={decision.confidence:.2f}]")
    print(_BORDER)


def run_interactive(detector: EscalationDetector) -> None:
    print("Agentic Escalation Detector — Interactive Mode")
    print("Type your message and press Enter. The bot will echo it back.")
    print("Type 'quit' or Ctrl-C to exit.\n")
    history: list[Message] = []

    # Opening bot greeting
    bot_greeting = "Hello! I'm here to help. What can I assist you with today?"
    print(f"BOT: {bot_greeting}")
    history.append(Message(role="bot", message=bot_greeting))

    while True:
        try:
            user_input = input("YOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if user_input.lower() in {"quit", "exit", "q"}:
            print("Goodbye.")
            break
        if not user_input:
            continue

        history.append(Message(role="user", message=user_input))

        decision = detector.check(history)
        _print_decision(decision)

        if decision.escalate:
            print("Transferring you to a human agent. Goodbye.")
            break

        # Stub bot reply (echo) so the detector has bot context on next turn
        bot_reply = f"Thank you for sharing that. Let me help you with: '{user_input}'"
        print(f"BOT: {bot_reply}")
        history.append(Message(role="bot", message=bot_reply))


def run_replay(detector: EscalationDetector, data_path: Path, conv_id: str) -> None:
    history = _load_conversation(data_path, conv_id)
    print(f"Agentic Escalation Detector — Replaying conversation '{conv_id}'")
    print(_BORDER)

    accumulated: list[Message] = []
    escalated_at: int | None = None

    for i, turn in enumerate(history):
        role_label = "BOT" if turn.role == "bot" else "YOU"
        print(f"{role_label}: {turn.message}")
        accumulated.append(turn)

        if turn.role == "user" and escalated_at is None:
            decision = detector.check(accumulated)
            _print_decision(decision)
            if decision.escalate:
                escalated_at = i + 1
                print(f"[Detector would have escalated at turn {escalated_at}]")
                break
        else:
            print()

    if escalated_at is None:
        print(f"\n✅  No escalation triggered after {len(history)} turns.")


def build_detector(llm_only: bool, skip_nli: bool = False) -> EscalationDetector:
    intent = None if (skip_nli or llm_only) else load_intent_classifier()
    rule_engine = None if llm_only else RuleEngine(intent_classifier=intent)
    return EscalationDetector(
        rule_engine=rule_engine,
        llm_classifier=create_classifier(load_llm_config()),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic escalation detector CLI")
    parser.add_argument(
        "--replay", metavar="CONV_ID",
        help="Replay a labeled conversation (e.g. c001)",
    )
    parser.add_argument(
        "--data", metavar="PATH", default=str(_DEFAULT_DATA),
        help="Path to the dataset JSON",
    )
    parser.add_argument(
        "--llm-only", action="store_true",
        help="Skip Tier 1 rules; use LLM for every turn",
    )
    parser.add_argument(
        "--no-nli", action="store_true",
        help="Use regex fallback instead of NLI for explicit-request detection",
    )
    args = parser.parse_args()

    try:
        detector = build_detector(llm_only=args.llm_only, skip_nli=args.no_nli)
    except EnvironmentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    data_path = Path(args.data)

    if args.replay:
        try:
            run_replay(detector, data_path, args.replay)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        run_interactive(detector)


if __name__ == "__main__":
    main()
