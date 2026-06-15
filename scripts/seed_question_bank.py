"""Populate the QuestionBank from every *.json file in questions/.

Idempotent: only ADDS questions whose text isn't already in the bank (matched
by question_ar). Never deletes existing rows — that's the consumption path.

Each JSON file is a list of objects shaped like:
    { "question": "...", "options": ["a","b",...], "correctAnswer": "...",
      "difficulty"|"level": "..." (optional), "id": ..., "worldCup": ... }
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, QuestionBank


QUESTIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "questions")


def _normalize(raw):
    """Return (question, choices, correct_index, difficulty) or None to skip."""
    q = (raw.get("question") or "").strip()
    opts = raw.get("options") or []
    ans = raw.get("correctAnswer")
    diff = raw.get("difficulty") or raw.get("level")
    if not q or not opts or ans is None:
        return None
    if len(opts) < 2:
        return None
    try:
        correct_index = opts.index(ans)
    except ValueError:
        return None
    return q, list(opts), correct_index, (str(diff) if diff else None)


def seed():
    with app.app_context():
        db.create_all()  # ensure tables exist
        existing = {row.question_ar for row in QuestionBank.query.all()}
        added = 0
        skipped_dupe = 0
        skipped_bad = 0
        for fn in sorted(os.listdir(QUESTIONS_DIR)):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(QUESTIONS_DIR, fn)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            rows = data if isinstance(data, list) else data.get("questions", [])
            file_added = 0
            for raw in rows:
                norm = _normalize(raw)
                if not norm:
                    skipped_bad += 1
                    continue
                q, opts, ci, diff = norm
                if q in existing:
                    skipped_dupe += 1
                    continue
                db.session.add(QuestionBank(
                    question_ar=q,
                    choices_json=json.dumps(opts, ensure_ascii=False),
                    correct_index=ci,
                    difficulty=diff,
                ))
                existing.add(q)
                added += 1
                file_added += 1
            print(f"  {fn}: +{file_added} new")
        db.session.commit()
        total = QuestionBank.query.count()
        print(f"Seed complete. Added: {added}, duplicates skipped: {skipped_dupe}, malformed: {skipped_bad}")
        print(f"Total in bank now: {total}")


if __name__ == "__main__":
    seed()
