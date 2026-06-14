# World Cup 2026 Predictor

A bilingual (English / Arabic) web app where friends predict 2026 FIFA World Cup matches and compete on points.

## Features

- Predict score, first goal scorer, and man of the match for every fixture
- Arabic trivia question per match, unlocked from 1 hour before kickoff
- Auto-scoring (+3 exact score / first scorer / MOTM / trivia, +1 winner-only bonus)
- Predictions lock at kickoff
- 12 group stage + full knockout bracket (48 teams)
- Admin panel: manage matches, enter results, set trivia, view all predictions
- Live countdown timers, mobile responsive, English ⇄ Arabic with RTL

## Local Setup (Windows)

1. Install Python 3.11+ from python.org.
2. Double-click **`seed_database.bat`** — creates the virtualenv, installs deps, loads teams/players/matches, creates admin accounts.
3. Double-click **`start_server.bat`** — starts the app at <http://localhost:5000>.

### Default admin accounts

| Username | Password |
| --- | --- |
| anas | admin123 |
| odai | admin123 |
| ali | admin123 |
| mohammad_hariri | admin123 |

Change passwords from the profile page (or update `DEFAULT_ADMIN_PASSWORD` in `scripts/seed.py` before seeding).

## Manual / Linux / Mac Setup

```bash
python -m venv .venv
source .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
python scripts/seed.py
python app.py
```

## Refreshing data from football-data.org

The bundled `data/teams.json` ships with a placeholder draw. To pull the **real** 2026 World Cup teams, fixtures, and live status:

1. Get a free API key at <https://www.football-data.org/client/register> (no credit card).
2. Copy `.env.example` → `.env` and paste your key into `FOOTBALL_DATA_API_KEY`.
3. Run the refresher:

   ```bash
   # Fast: teams + fixtures only (~10 sec)
   python scripts/fetch_fifa_data.py --skip-squads

   # Full: also pulls all 48 squads (~5 min due to free-tier rate limit of 10 req/min)
   python scripts/fetch_fifa_data.py
   ```

4. Reseed:

   ```bash
   rm worldcup.db instance/worldcup.db   # drop the old DB
   python scripts/seed.py                # load the fresh data
   ```

The fetcher writes `data/teams.json`, `data/matches.json`, and `data/players_stars.json`. Arabic team names you've already translated are preserved across refreshes.

To pick up **live status changes** during the tournament (UPCOMING → LIVE → FINISHED) without nuking predictions, re-run the fetcher and call a future `--update-status-only` flag (not implemented yet — current behaviour is full reseed). For now, admins can flip status manually via the admin matches page.

## Deploying to Render

1. Push this repo to GitHub.
2. In Render: **New → Blueprint**, pick the repo. `render.yaml` provisions a free web service + free Postgres.
3. After first deploy, open the Render shell and run:

   ```bash
   python scripts/seed.py
   ```

That populates the production DB.

## Tech

Flask + Flask-Login + Flask-SQLAlchemy. SQLite locally, Postgres on Render. Jinja templates with Tailwind via CDN. Vanilla JS countdown.

## Scoring

| Correct prediction | Points |
| --- | --- |
| Exact final score | +3 |
| Winner only (no exact) | +1 |
| First goal scorer | +3 |
| Man of the match | +3 |
| Trivia answer | +3 |

Leaderboard ties broken by exact-score count, then earliest signup.

## Notes & Limitations

- **Player squads** include a curated set of stars plus numbered placeholders to fill 23-man rosters. Replace placeholders with real names in `data/players_stars.json` and re-seed when official squads are published.
- **Knockout bracket teams** are seeded as placeholders (group winners used as stand-ins). After the group stage, admins should edit each knockout match via the admin panel to point at the actual qualifying teams.
- **Trivia is Arabic-only** by design (requirement #3).
- **First boot** creates the SQLite DB and tables automatically — no migrations to run.
