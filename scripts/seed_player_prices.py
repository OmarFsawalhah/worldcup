"""Pre-fill players.price from data/player_prices.json — a curated list of
known WC2026 stars with rough fantasy prices.

Usage:
    python scripts/seed_player_prices.py            # apply to every match (fuzzy name)
    python scripts/seed_player_prices.py --dry-run  # show what would change

Anything not in the JSON keeps its current price (default €4.0).

Matching strategy (each player price entry tried in order):
  1. Exact name match (case-insensitive, accent-stripped)
  2. Last-name match (must be unique across DB)
  3. Token-overlap (≥2 shared tokens of length ≥3)
"""
import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import app
from models import db, Player


def _norm(s: str) -> str:
    """Lowercase, strip diacritics, collapse spaces."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _find_player(target: str, all_players: list) -> Player | None:
    t = _norm(target)
    if not t:
        return None

    # 1. Exact normalized match
    exact = [p for p in all_players if _norm(p.name_en) == t]
    if len(exact) == 1:
        return exact[0]

    # 2. Last-name match (last token of target)
    last = t.split()[-1] if t else ""
    if last and len(last) >= 3:
        hits = [p for p in all_players if last in _norm(p.name_en).split()]
        if len(hits) == 1:
            return hits[0]

    # 3. Token overlap ≥ 2 (length ≥ 3)
    t_tokens = {tok for tok in t.split() if len(tok) >= 3}
    best, best_score = None, 1
    for p in all_players:
        p_tokens = {tok for tok in _norm(p.name_en).split() if len(tok) >= 3}
        overlap = len(t_tokens & p_tokens)
        if overlap > best_score:
            best, best_score = p, overlap
    return best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without saving.")
    args = parser.parse_args()

    prices_path = os.path.join(ROOT, "data", "player_prices.json")
    if not os.path.exists(prices_path):
        print(f"Missing {prices_path}")
        sys.exit(1)

    with open(prices_path, encoding="utf-8") as fh:
        rows = json.load(fh)

    with app.app_context():
        all_players = Player.query.all()
        applied, missed, already_matched = 0, 0, set()
        for r in rows:
            name = r["name"].strip()
            price = float(r["price"])
            p = _find_player(name, all_players)
            if not p:
                missed += 1
                print(f"  miss  {name}")
                continue
            if p.id in already_matched:
                # Skip if this player got matched by an earlier alias — keep
                # the first hit's price.
                continue
            already_matched.add(p.id)
            old = float(p.price or 0)
            if abs(old - price) < 0.05:
                continue  # already correct
            print(f"  set   {name:35s} -> {p.name_en:35s}  €{old:>4.1f} -> €{price:>4.1f}")
            if not args.dry_run:
                p.price = price
            applied += 1
        if not args.dry_run:
            db.session.commit()
        print(f"\nDone. Applied {applied} updates, missed {missed} unknown names.")
        if args.dry_run:
            print("(dry run — no changes saved)")


if __name__ == "__main__":
    main()
