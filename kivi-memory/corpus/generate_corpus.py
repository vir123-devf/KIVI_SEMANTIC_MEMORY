"""
Generates a synthetic corpus of ~500 transcript-like records for one
persona, saved to corpus/data/records.json in the exact shape /ingest
expects.

Run: python -m corpus.generate_corpus
"""
import json
import os
import random
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.jsonutil import parse_json_payload
from app.llm import generate_text

SOURCE_APPS = ["slack", "gmail", "docs", "notes", "zoom"]

PERSONA_SEED = """
Persona: a product manager named Vir working at a mid-size fintech startup.
Known facts to weave in naturally across several dictations (not all at once):
- manager's name is Priya Nair
- current project codename is 'Falcon'
- team stands up at 9:30am daily
- Q3 revenue target is $2.4M (mentioned once, then later corrected to $2.6M in a later dictation)
Known preferences to reinforce across multiple dictations:
- prefers concise bullet points over long prose in written updates
- always signs off emails with 'Best, Vir'
- prefers direct, low-fluff tone in Slack messages
"""

BATCH_PROMPT = """{seed}

Generate {n} realistic short dictation transcripts (2-5 sentences each) for this persona,
covering a mix of: work updates, meeting notes, emails being dictated, casual Slack messages,
personal reminders. About 30% should contain a fact or preference from the list above stated
naturally (not all facts in one transcript). About 20% should contain NOTHING durable at all
(pure logistics, one-off tasks, greetings). Vary phrasing -- don't repeat sentences verbatim.

Return a JSON array of exactly {n} objects, each:
{{"raw_asr": "<lowercase, no punctuation, as raw speech-to-text would look>",
  "formatted_text": "<same content, properly punctuated/capitalized as Kivi would format it>",
  "source_app": "<one of: slack, gmail, docs, notes, zoom>"}}

Return ONLY the JSON array."""


def generate_batch(n: int) -> list[dict]:
    text = generate_text(
        BATCH_PROMPT.format(seed=PERSONA_SEED, n=n),
        model=settings.EXTRACTION_MODEL,
        max_tokens=4096,
    )
    data = parse_json_payload(text)
    if not isinstance(data, list):
        raise ValueError("corpus batch was not a JSON array")
    return data


def main(total: int = 500, batch_size: int = 25):
    records = []
    base_time = datetime.now(timezone.utc) - timedelta(days=90)

    while len(records) < total:
        n = min(batch_size, total - len(records))
        batch = generate_batch(n)
        for item in batch:
            occurred_at = base_time + timedelta(
                days=random.randint(0, 90),
                hours=random.randint(7, 20),
                minutes=random.randint(0, 59),
            )
            records.append({
                "occurred_at": occurred_at.isoformat(),
                "source_app": item.get("source_app", random.choice(SOURCE_APPS)),
                "raw_asr": item["raw_asr"],
                "formatted_text": item["formatted_text"],
            })
        print(f"generated {len(records)}/{total}")

    records.sort(key=lambda r: r["occurred_at"])
    os.makedirs("corpus/data", exist_ok=True)
    with open("corpus/data/records.json", "w") as f:
        json.dump(records, f, indent=2)
    print(f"wrote {len(records)} records to corpus/data/records.json")


if __name__ == "__main__":
    main()
