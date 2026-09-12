"""
Generates ~500 synthetic dictation records for one user, deliberately
seeded with recoverable facts/preferences/episodes so the eval harness has
known-answer questions to check against.

Deterministic (seeded RNG) so the corpus is reproducible without an LLM
call, per the brief's "not treating this as a data-generation competition."
A small fraction of records are intentionally noisy/irrelevant filler, so
retrieval has to actually discriminate rather than everything being signal.
"""
import json
import random
import uuid
from datetime import datetime, timedelta, timezone

random.seed(42)

APPS = ["Slack", "Gmail", "Notion", "Docs", "Linear", "Calendar"]

# Ground-truth signals deliberately planted, distributed across many records
# (so recovery requires aggregation, not a single lucky match).
PREFERENCE_TEMPLATES = [
    "Always sign off emails with 'Best, Vir' rather than 'Thanks'.",
    "For Slack status updates, keep it to three bullet points, no preamble.",
    "When polishing meeting notes, use action-item format with owners tagged.",
    "Prefers British spelling in formal documents.",
]
FACT_TEMPLATES = [
    "The Q3 launch project is internally called 'Project Kingfisher'.",
    "Priya is the design lead on the onboarding redesign.",
    "The weekly sync with the data team is every Thursday.",
    "The client account for the biggest deal this quarter is Meridian Corp.",
]
FILLER_TOPICS = [
    "grocery list for the week", "a reminder to book a dentist appointment",
    "notes on a podcast episode about urban planning", "a rough draft of a birthday message",
    "brainstorming names for a side project", "a recap of a documentary about deep sea life",
]


def make_ts(days_ago: float) -> str:
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return ts.isoformat()


def gen_preference_dictation(i, days_ago):
    tmpl = random.choice(PREFERENCE_TEMPLATES)
    raw = f"uh so just a note to self {tmpl.lower().replace('.', '')} okay thanks"
    formatted = f"Note to self: {tmpl}"
    return dict(ts=make_ts(days_ago), app_context=random.choice(APPS),
                raw_asr=raw, llm_formatted=formatted,
                meta={"seed_type": "preference", "seed_id": i})


def gen_fact_dictation(i, days_ago):
    tmpl = random.choice(FACT_TEMPLATES)
    raw = f"quick note {tmpl.lower().replace('.', '')} for reference later"
    formatted = f"{tmpl}"
    return dict(ts=make_ts(days_ago), app_context=random.choice(APPS),
                raw_asr=raw, llm_formatted=formatted,
                meta={"seed_type": "fact", "seed_id": i})


def gen_episodic_dictation(i, days_ago, app):
    topics = [
        ("a status update about the Q3 launch", "Kingfisher is on track; frontend done, backend in QA."),
        ("a draft reply to the Meridian Corp contract question", "Confirming the revised timeline works on our end."),
        ("talking points for the onboarding redesign review", "Walking through the three flows Priya's team shipped."),
    ]
    subject, body = random.choice(topics)
    raw = f"okay dictating {subject} um {body.lower()}"
    formatted = f"{subject.capitalize()}: {body}"
    return dict(ts=make_ts(days_ago), app_context=app,
                raw_asr=raw, llm_formatted=formatted,
                meta={"seed_type": "episodic", "seed_id": i})


def gen_filler_dictation(i, days_ago):
    topic = random.choice(FILLER_TOPICS)
    raw = f"um just dictating {topic} nothing important"
    formatted = f"Note: {topic}."
    return dict(ts=make_ts(days_ago), app_context=random.choice(APPS),
                raw_asr=raw, llm_formatted=formatted,
                meta={"seed_type": "filler", "seed_id": i})


def generate(n=500):
    records = []
    # Plant the "find the dictation I did around 5pm yesterday in Slack"
    # example from the brief explicitly, at a known timestamp.
    yesterday_5pm = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
        hour=17, minute=4, second=0, microsecond=0)
    records.append(dict(
        ts=yesterday_5pm.isoformat(), app_context="Slack",
        raw_asr="okay dictating a status update about the q3 launch kingfisher is on track frontend done backend in qa",
        llm_formatted="Status update on Project Kingfisher: frontend is done, backend is in QA.",
        meta={"seed_type": "anchor_episodic", "seed_id": "anchor"},
    ))

    for i in range(n - 1):
        days_ago = random.uniform(0.1, 90)
        roll = random.random()
        if roll < 0.12:
            records.append(gen_preference_dictation(i, days_ago))
        elif roll < 0.24:
            records.append(gen_fact_dictation(i, days_ago))
        elif roll < 0.40:
            records.append(gen_episodic_dictation(i, days_ago, random.choice(APPS)))
        else:
            records.append(gen_filler_dictation(i, days_ago))

    records.sort(key=lambda r: r["ts"])
    return records


if __name__ == "__main__":
    data = generate(500)
    with open("corpus.jsonl", "w") as f:
        for r in data:
            f.write(json.dumps(r) + "\n")
    print(f"Wrote {len(data)} records to corpus.jsonl")
