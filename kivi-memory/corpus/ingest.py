"""
Loads a corpus JSON file and ingests it via the running API's /ingest
endpoint, in batches (avoids one giant request timing out on ~500 LLM calls).

Usage:
    python -m corpus.ingest --user-id <uuid> --file corpus/data/records.json
"""
import argparse
import json
import uuid as uuid_lib

import requests

API_URL = "http://localhost:8000"
BATCH_SIZE = 20


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", default=None, help="UUID to ingest as; generated if omitted")
    parser.add_argument("--file", default="corpus/data/records.json")
    args = parser.parse_args()

    user_id = args.user_id or str(uuid_lib.uuid4())
    print(f"Ingesting as user_id={user_id}")

    with open(args.file) as f:
        records = json.load(f)

    totals = {"episodes_created": 0, "facts_created": 0, "preferences_created": 0}
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        resp = requests.post(
            f"{API_URL}/ingest",
            json={"user_id": user_id, "records": batch},
            timeout=600,
        )
        resp.raise_for_status()
        result = resp.json()
        for k in totals:
            totals[k] += result[k]
        print(f"batch {i // BATCH_SIZE + 1}: {result}")

    print(f"\nDone. Totals: {totals}")
    print(f"user_id for querying Hey Kivi / inspecting memory: {user_id}")


if __name__ == "__main__":
    main()
