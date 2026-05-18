#!/usr/bin/env python3
"""
Offline evaluation of the escalation detector against the labeled dataset.

Metrics reported: accuracy, precision, recall, F1.
Per-conversation results show which tier fired and the reason, making it easy
to inspect misclassifications and tune thresholds.

Usage:
  python evaluate.py
  python evaluate.py --data path/to/data.json
  python evaluate.py --rules-only        # Tier 1 alone (no LLM cost)
  python evaluate.py --llm-only          # Tier 2 alone (skip rule engine)
  python evaluate.py --no-nli            # regex fallback instead of NLI
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from escalation import EscalationDetector, Message
from escalation.config import load_llm_config
from escalation.llm_classifier import create_classifier
from escalation.rules import load_intent_classifier, RuleEngine

_DEFAULT_DATA = Path(__file__).parent / "data" / "escalation_dataset.json"


@dataclass
class ConvResult:
    conv_id: str
    label: bool
    predicted: bool
    tier: str
    reason: str
    confidence: float
    latency_ms: float = 0.0

    @property
    def correct(self) -> bool:
        return self.label == self.predicted


def load_dataset(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def build_detector(rules_only: bool, llm_only: bool, skip_nli: bool = False) -> tuple[EscalationDetector, bool]:
    intent = None if (skip_nli or llm_only) else load_intent_classifier()
    rule_engine = None if llm_only else RuleEngine(intent_classifier=intent)
    llm_classifier = None if rules_only else create_classifier(load_llm_config())
    return EscalationDetector(rule_engine=rule_engine, llm_classifier=llm_classifier), intent is not None


def evaluate(detector: EscalationDetector, dataset: list[dict]) -> list[ConvResult]:
    results = []
    for conv in dataset:
        history = [Message(role=m["role"], message=m["message"]) for m in conv["conversation_history"]]
        label = bool(conv["is_escalation_needed"])
        t0 = time.perf_counter()
        decision = detector.check(history)
        latency_ms = (time.perf_counter() - t0) * 1000
        results.append(ConvResult(
            conv_id=conv["conversation_id"],
            label=label,
            predicted=decision.escalate,
            tier=decision.tier,
            reason=decision.reason,
            confidence=decision.confidence,
            latency_ms=latency_ms,
        ))
    return results


def _percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolation percentile (matches numpy's default method)."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    idx = (p / 100) * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    return sorted_values[lo] + (idx - lo) * (sorted_values[hi] - sorted_values[lo])


def compute_metrics(results: list[ConvResult]) -> dict:
    tp = sum(1 for r in results if r.label and r.predicted)
    tn = sum(1 for r in results if not r.label and not r.predicted)
    fp = sum(1 for r in results if not r.label and r.predicted)
    fn = sum(1 for r in results if r.label and not r.predicted)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(results) if results else 0.0

    latencies = sorted(r.latency_ms for r in results)
    return dict(
        tp=tp, tn=tn, fp=fp, fn=fn,
        precision=precision, recall=recall, f1=f1, accuracy=accuracy,
        latency_p50_ms=round(_percentile(latencies, 50), 2),
        latency_p99_ms=round(_percentile(latencies, 99), 2),
        latency_min_ms=round(latencies[0], 2) if latencies else 0.0,
        latency_max_ms=round(latencies[-1], 2) if latencies else 0.0,
    )


def print_report(results: list[ConvResult], metrics: dict) -> None:
    print("\n" + "═" * 70)
    print(f"{'ID':<8} {'Label':<8} {'Pred':<8} {'Tier':<7} {'OK':<5} Reason")
    print("─" * 70)
    for r in results:
        label_str = "ESC" if r.label else "ok"
        pred_str = "ESC" if r.predicted else "ok"
        ok_str = "✓" if r.correct else "✗"
        reason = r.reason[:45] + "…" if len(r.reason) > 46 else r.reason
        print(f"{r.conv_id:<8} {label_str:<8} {pred_str:<8} {r.tier:<7} {ok_str:<5} {reason}")

    m = metrics
    print("═" * 70)
    print(f"\nResults over {len(results)} conversations:")
    print(f"  Accuracy : {m['accuracy']:.2%}  ({m['tp']+m['tn']}/{len(results)} correct)")
    print(f"  Precision: {m['precision']:.2%}  (of predicted ESC, how many were right)")
    print(f"  Recall   : {m['recall']:.2%}  (of true ESC, how many we caught)")
    print(f"  F1       : {m['f1']:.2%}")
    print(f"\n  TP={m['tp']}  TN={m['tn']}  FP={m['fp']}  FN={m['fn']}")

    print(f"\n  Latency per conversation (wall-clock, n={len(results)}):")
    print(f"    p50={m['latency_p50_ms']:.1f} ms   p99={m['latency_p99_ms']:.1f} ms"
          f"   min={m['latency_min_ms']:.1f} ms   max={m['latency_max_ms']:.1f} ms")

    misses = [r for r in results if not r.correct]
    if misses:
        print("\nMisclassifications:")
        for r in misses:
            direction = "FP (false-escalation)" if r.predicted else "FN (missed)"
            print(f"  {r.conv_id}: {direction} — {r.reason}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate escalation detector on the labeled dataset")
    parser.add_argument("--data", metavar="PATH", default=str(_DEFAULT_DATA))
    parser.add_argument("--output", metavar="PATH", default=None, help="Save results + metrics to a JSON file")
    parser.add_argument("--rules-only", action="store_true", help="Run Tier 1 only (no LLM)")
    parser.add_argument("--llm-only", action="store_true", help="Run Tier 2 only (no rules)")
    parser.add_argument("--no-nli", action="store_true", help="Use regex fallback instead of NLI for explicit-request detection")
    args = parser.parse_args()

    if args.rules_only and args.llm_only:
        print("Error: --rules-only and --llm-only are mutually exclusive.", file=sys.stderr)
        sys.exit(1)

    dataset = load_dataset(Path(args.data))
    print(f"Loaded {len(dataset)} conversations from {args.data}")

    try:
        detector, nli_active = build_detector(rules_only=args.rules_only, llm_only=args.llm_only, skip_nli=args.no_nli)
    except EnvironmentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    nli_tag = "+nli" if nli_active else ""
    mode = ("rules-only" if args.rules_only else ("llm-only" if args.llm_only else "two-tier")) + nli_tag
    print(f"Mode: {mode}\nRunning evaluation…")

    results = evaluate(detector, dataset)
    metrics = compute_metrics(results)
    print_report(results, metrics)

    if args.output:
        payload = {
            "mode": mode,
            "metrics": metrics,
            "results": [
                {"id": r.conv_id, "label": r.label, "predicted": r.predicted,
                 "tier": r.tier, "confidence": r.confidence, "reason": r.reason,
                 "latency_ms": round(r.latency_ms, 2)}
                for r in results
            ],
        }
        Path(args.output).write_text(json.dumps(payload, indent=2))
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
