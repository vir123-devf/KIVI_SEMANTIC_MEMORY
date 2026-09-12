"""
Runs the curated question set against the live Hey Kivi API for a given
ingested user, and scores each response on:
  - grounded: did every cited ID actually get returned by a tool call in
    the trace (i.e. is the citation real, not hallucinated)?
  - keyword_match: does the answer contain the expected substring (loose
    correctness check -- not a substitute for grounding, just a sanity signal)
  - correct_abstention: for questions with no answer in the corpus, did the
    system say so instead of inventing something?

Usage:
    python -m eval.run_eval --user-id <uuid>

Writes eval/results.json with full per-question detail (input, tool trace,
answer, citations, pass/fail, latency) so every result is inspectable.
"""
import argparse
import json

import requests

API_URL = "http://localhost:8000"


def check_grounding(response: dict) -> bool:
    """A citation is 'real' if the cited ID appears somewhere in the tool
    trace's results -- i.e. the model didn't cite an ID it made up."""
    cited_ids = set(
        response.get("cited_episode_ids", [])
        + response.get("cited_fact_ids", [])
        + response.get("cited_preference_ids", [])
    )
    if not cited_ids:
        return True  # nothing cited -- vacuously fine, judged separately by keyword/abstention checks

    seen_ids = set()
    for call in response.get("tool_trace", []):
        for r in call.get("result", {}).get("results", []):
            for key in ("episode_id", "fact_id", "preference_id"):
                if key in r:
                    seen_ids.add(r[key])

    return cited_ids.issubset(seen_ids)


def run(user_id: str):
    with open("eval/questions.json") as f:
        questions = json.load(f)

    results = []
    for q in questions:
        resp = requests.post(
            f"{API_URL}/hey-kivi", json={"user_id": user_id, "message": q["question"]}
        )
        resp.raise_for_status()
        data = resp.json()

        answer_lower = data["answer"].lower()
        keyword_match = (
            any(kw.lower() in answer_lower for kw in q["expects_answer_contains"])
            if q["expects_answer_contains"] else None
        )
        abstained = any(
            phrase in answer_lower
            for phrase in ["don't have", "do not have", "no information", "couldn't find", "not sure", "unable to find"]
        )

        result = {
            "id": q["id"],
            "question": q["question"],
            "answer": data["answer"],
            "cited_episode_ids": data["cited_episode_ids"],
            "cited_fact_ids": data["cited_fact_ids"],
            "cited_preference_ids": data["cited_preference_ids"],
            "tool_trace": data["tool_trace"],
            "latency_ms": data["latency_ms"],
            "grounded": check_grounding(data),
            "keyword_match": keyword_match,
            "no_answer_expected": q["no_answer_expected"],
            "correctly_abstained": abstained if q["no_answer_expected"] else None,
            "passed": None,  # computed below
        }

        if q["no_answer_expected"]:
            result["passed"] = result["grounded"] and abstained
        else:
            result["passed"] = result["grounded"] and (keyword_match is not False)

        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {q['id']}: {q['question']}")

    n_pass = sum(1 for r in results if r["passed"])
    avg_latency = sum(r["latency_ms"] for r in results) / len(results)

    summary = {
        "total": len(results),
        "passed": n_pass,
        "pass_rate": n_pass / len(results),
        "avg_latency_ms": avg_latency,
    }
    print(f"\n{summary}")

    with open("eval/results.json", "w") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2)
    print("Full results written to eval/results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    args = parser.parse_args()
    run(args.user_id)
