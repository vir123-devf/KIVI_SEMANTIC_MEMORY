"""
Runs a fixed set of questions against a running Hey Kivi instance and checks:
  1. Did it call a tool at all where one was needed?
  2. Is the answer grounded (did it retrieve non-empty results before
     answering, for questions with a known answer in the corpus)?
  3. For the deliberate no-answer probes, did it correctly refuse rather
     than invent something?
  4. Latency / token cost per turn.

This is a coarse, mechanical check (keyword presence + grounding-state),
not a semantic grader -- intentionally, so failures are transparent rather
than hidden behind another LLM's judgment call. Read report.json for the
full trace of every turn (tool calls, retrieved memory ids, reasoning).

Usage:
    python run_eval.py [--base-url http://localhost:8000]
"""
import argparse
import json
import time
import requests

CASES = [
    {
        "id": "anchor_episodic_recall",
        "query": "Find the dictation I did around 5 PM yesterday in Slack and polish it for the meeting I'm walking into.",
        "expect_grounded": True,
        "expect_keywords": ["kingfisher"],
    },
    {
        "id": "preference_recall",
        "query": "How do I usually sign off emails?",
        "expect_grounded": True,
        "expect_keywords": ["vir"],
    },
    {
        "id": "fact_recall_cross_dictation",
        "query": "Who's the design lead on the onboarding redesign, and what's our biggest client account called this quarter?",
        "expect_grounded": True,
        "expect_keywords": ["priya", "meridian"],
    },
    {
        "id": "explicit_remember",
        "query": "Remember that I prefer to be called 'V' in casual Slack messages.",
        "expect_grounded": False,
        "expect_keywords": [],
        "expect_tool": "remember",
    },
    {
        "id": "no_answer_probe",
        "query": "What did I say about my favorite restaurant in Lisbon?",
        "expect_grounded": False,
        "expect_refusal": True,
    },
    {
        "id": "explicit_forget_followup",
        "query": "Forget that I prefer British spelling.",
        "expect_grounded": True,
        "expect_tool": "forget",
    },
]

REFUSAL_MARKERS = ["don't have", "not in", "no record", "couldn't find", "don't see", "not sure"]


def run(base_url: str):
    results = []
    for case in CASES:
        start = time.time()
        resp = requests.post(f"{base_url}/hey_kivi", json={"query": case["query"]}, timeout=60)
        elapsed_ms = int((time.time() - start) * 1000)
        data = resp.json()
        answer = data.get("response", "")
        tool_names = [t["name"] for t in data.get("tool_calls", [])]

        checks = {}
        if "expect_tool" in case:
            checks["called_expected_tool"] = case["expect_tool"] in tool_names
        if case.get("expect_grounded"):
            checks["retrieved_something"] = len(data.get("retrieved_memory_ids", [])) > 0
        if case.get("expect_keywords"):
            lower = answer.lower()
            checks["keywords_present"] = all(k in lower for k in case["expect_keywords"])
        if case.get("expect_refusal"):
            checks["correctly_refused"] = any(m in answer.lower() for m in REFUSAL_MARKERS)

        results.append({
            "case_id": case["id"], "query": case["query"], "answer": answer,
            "tool_calls": tool_names, "retrieved_memory_ids": data.get("retrieved_memory_ids", []),
            "reasoning": data.get("reasoning"), "checks": checks,
            "passed": all(checks.values()) if checks else None,
            "server_latency_ms": data.get("latency_ms"), "wall_latency_ms": elapsed_ms,
            "input_tokens": data.get("input_tokens"), "output_tokens": data.get("output_tokens"),
        })
        print(f"[{case['id']}] passed={all(checks.values()) if checks else 'n/a'} "
              f"latency={elapsed_ms}ms tools={tool_names}")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--out", default="report.json")
    args = parser.parse_args()

    results = run(args.base_url)
    n_pass = sum(1 for r in results if r["passed"])
    n_total = sum(1 for r in results if r["passed"] is not None)
    summary = {
        "passed": n_pass, "total_checked": n_total,
        "avg_latency_ms": sum(r["wall_latency_ms"] for r in results) / len(results),
        "total_input_tokens": sum(r["input_tokens"] or 0 for r in results),
        "total_output_tokens": sum(r["output_tokens"] or 0 for r in results),
    }
    with open(args.out, "w") as f:
        json.dump({"summary": summary, "cases": results}, f, indent=2)
    print(f"\n{n_pass}/{n_total} checks passed. Full report: {args.out}")


if __name__ == "__main__":
    main()
