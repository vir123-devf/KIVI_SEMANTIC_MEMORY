"""
Imports a JSONL corpus of dictation records into the running backend via its
HTTP API (so import exercises the exact same extraction pipeline as live use).

Expected record shape (extra fields are preserved in `meta`, unknown fields
ignored):
{
  "ts": "<ISO8601 timestamp>",
  "app_context": "<string, optional>",
  "raw_asr": "<string>",
  "llm_formatted": "<string>",
  ...any other metadata...
}

If the reviewer's internal corpus uses different field names, map them
below in `normalize_record` -- this is the single place to edit for a new
corpus shape.

Usage:
    python import_corpus.py path/to/corpus.jsonl [--base-url http://localhost:8000]
"""
import argparse
import json
import sys
import time
import requests


def normalize_record(raw: dict) -> dict:
    return {
        "ts": raw.get("ts") or raw.get("timestamp"),
        "app_context": raw.get("app_context") or raw.get("app") or raw.get("source"),
        "raw_asr": raw.get("raw_asr") or raw.get("asr_output") or "",
        "llm_formatted": raw.get("llm_formatted") or raw.get("formatted_output") or raw.get("raw_asr", ""),
        "meta": {k: v for k, v in raw.items()
                 if k not in {"ts", "timestamp", "app_context", "app", "source",
                              "raw_asr", "asr_output", "llm_formatted", "formatted_output"}},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_path")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    ok, failed = 0, 0
    start = time.time()
    with open(args.corpus_path) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                record = normalize_record(raw)
                resp = requests.post(f"{args.base_url}/dictations", json=record, timeout=60)
                resp.raise_for_status()
                ok += 1
            except Exception as e:
                failed += 1
                print(f"[line {line_no}] failed: {e}", file=sys.stderr)
            if line_no % 50 == 0:
                print(f"...{line_no} processed ({ok} ok, {failed} failed)")

    elapsed = time.time() - start
    print(f"Done. {ok} imported, {failed} failed, {elapsed:.1f}s total "
          f"({elapsed / max(ok, 1):.2f}s/record).")


if __name__ == "__main__":
    main()
