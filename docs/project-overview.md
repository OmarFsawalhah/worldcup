# World Cup 2026 Predictor — Project Overview

> **Source of truth for the non-fantasy core of this app.**
> Future Claude sessions: **read this first** before touching prediction / trivia / leaderboard / admin code. For anything inside the fantasy game, read `docs/fantasy-build-log.md` instead.

---

## What this app is

A bilingual (English / Arabic, RTL-aware) Flask app where a small group of friends predict every match of the **2026 FIFA World Cup** and compete on a points leaderboard. The Fantasy game (FPL-style squad) is a separate feature built on top of the same data and lives in its own log file.

Stack:
- **Backend:** Flask + Flask-Login + Flask-SQLAlchemy
- **DB:** SQLite locally (`worldcup.db`), Postgres on Render in production
- **Frontend:** Jinja templates + Tailwind via CDN + vanilla JS (no build step)
- **i18n:** `translations/en.json` + `translations/ar.json`, loaded by `i18n.py`, used in templates as `{{ t('key') }}` and Python as `t('key')`

Entry point: `app.py` → `create_app()` → registers blueprints `auth`, `public`, `admin`. (The `fantasy` blueprint exists only on the `fantasy-mvp` branch — not on `main`.)

---

## Repo layout (non-fantasy parts)

```
app.py                  Flask factory + auto-migrate + lang switcher
models.py               All SQLAlchemy models (incl. fantasy ones — same file)
scoring.py              Prediction scoring engine (pure functions)
i18n.py                 Translation loader + t() helper
routes/
  auth.py               login / register / logout / change-password
  public.py             dashboard / match detail / leaderboard / profile
  admin.py              matches CRUD, results, points calc, users, predictions log
  (fantasy.py)          only on fantasy-mvp branch — see fantasy-build-log.md
services/
  api_refresh.py        Pulls live status/scores from football-data.org
templates/              Jinja templates (admin/ subdir for admin pages)
translations/           en.json + ar.json
scripts/
  seed.py               Loads teams / players / matches from data/*.json, creates admins
  fetch_fifa_data.py    Pulls real WC2026 data from football-data.org
  seed_question_bank.py Loads trivia pool
  diagnose_api.py / test_e2e.py
data/                   teams.json, matches.json, players_stars.json, etc.
seed_database.bat       Windows: venv + deps + seed
start_server.bat        Windows: starts dev server on :5000
render.yaml             Render Blueprint (web + free Postgres)
```

---

## Domain model — what each table holds

All models live in `models.py`. On `main` the active models are:

| Model | Purpose |
|---|---|
| `User` | Username (lowercase, unique), password hash, `is_admin`, `is_superuser`, `must_change_password`, `bonus_points` (manual adjust) |
| `Team` | `code` (3-letter), `name_en` / `name_ar`, `flag_emoji` (regional-indicator pair), `group_letter` |
| `Player` | Belongs to a Team. `name_en` / `name_ar`, `position`, `shirt_number` |
| `Match` | `stage` (group/r32/r16/qf/sf/third/final), optional `group_letter`, home/away teams, `kickoff_utc`, `venue`, `status`, `home_score`/`away_score`, `first_scorer_id`, `motm_id`, `calculated_by_id` |
| `Prediction` | One per (user, match). `winner_prediction` ∈ {home,draw,away,NULL}, optional `home_score`/`away_score`, optional `first_scorer_id` / `motm_id`, cached `points_awarded` |
| `TriviaQuestion` / `TriviaAnswer` / `QuestionBank` / `MatchTrivia` | **Dormant.** Trivia UI + scoring were removed in commit `d23f6a3`; tables are kept so historical data and per-user point logs still work. Don't add new code against them. |

The fantasy-only models (`FantasySquad`, `FantasyPick`, `MatchEvent`) and Player extensions (`price`, `photo_url`) live on the `fantasy-mvp` branch and are documented in `fantasy-build-log.md`.

Key relationships:
- `Match.predictions` (one-to-many, cascade delete)
- `Match.trivia` (one-to-one, legacy)
- `User.predictions`, `User.trivia_answers`

### Important quirks
- **Usernames are stored lowercase.** Login does `username.strip().lower()` before lookup (`routes/auth.py:13`). Any rename via the DB must also be lowercase, no spaces, or the user can't log in.
- **`kickoff_utc` is naive UTC.** `Match.kickoff_aware()` wraps it with `tzinfo=UTC` for comparisons.
- **`Match.is_locked()`** = `utcnow() >= kickoff_aware()`. Predictions can't be edited after that.
- **Auto-migration** runs at boot (`_auto_migrate()` in `app.py`) — only additive `ALTER TABLE ADD COLUMN` for known fields. No Alembic.

---

## Scoring rules (prediction game) — locked

Implemented in `scoring.py`. **The README is out of date on this** — the code is the source of truth.

| Correct prediction | Points |
|---|---|
| Winner / draw correct | **+3** (`POINTS_WINNER`) |
| **Also** exact score (only on top of a winner hit) | **+2** (`POINTS_EXACT_BONUS`) |
| First goal scorer | **+3** (`POINTS_FIRST_SCORER`) |
| Man of the match | **+3** (`POINTS_MOTM`) |
| ~~Trivia answer correct~~ | ~~+3~~ — **removed on main in `d23f6a3`**. Code path no longer reads `MatchTrivia` / `TriviaAnswer`. |
| Manual admin bonus | `User.bonus_points` (free-form integer) |

`score_match(match)` recomputes `Prediction.points_awarded` for every prediction on the match. **Safe to re-run** — it overwrites. Triggered from the admin "Calculate points" button. The admin who first hit calculate is recorded in `Match.calculated_by_id`; only that admin (or a superuser) can recalc.

`user_total_points(user_id)` = sum(prediction points) + `bonus_points`.

Leaderboard tie-break: by **exact-score-hits desc**, then earliest signup.

---

## User roles

Three levels, all flags on `User`:

| Role | Flag | What they can do |
|---|---|---|
| Regular | (none) | Predict, view leaderboard, profile |
| **Admin** | `is_admin` | Everything above, **plus**: manage matches, enter results, calculate points, edit fantasy players/events, view all predictions on a match |
| **Superuser** | `is_superuser` | Everything above, **plus**: view any user's full breakdown (`/admin/users/<id>`), see the points-log timeline (`/admin/points-log`), force-recalc a match already calculated by another admin |

Superusers are **hidden from both leaderboards** (main + fantasy) to keep dev/test accounts off the rankings.

Decorators in `routes/admin.py`: `@admin_required`, `@superuser_required`. Both wrap `@login_required`.

`must_change_password=True` forces a redirect to `/change-password` on every request until they set a new one — used when an admin resets someone's password (`app.py:_enforce_password_change`).

---

## Routes — what each blueprint owns

### `auth` (`routes/auth.py`)
- `GET/POST /login` — username lowercased, password checked with werkzeug
- `GET/POST /register` — open registration (no admin gate)
- `GET /logout`
- `GET/POST /change-password` — also clears `must_change_password`

### `public` (`routes/public.py`)
- `GET /` → dashboard. If not logged in → `/login`. Lists all matches grouped by stage + group letter. Shows which the user has predicted (`predicted_ids` set).
- `GET/POST /match/<id>` — combined match detail + prediction wizard. POST with `action=predict|wizard` saves the prediction. Refuses if locked.
- `GET /leaderboard` — sorted by points desc, exact-hits desc, earliest signup. Excludes superusers.
- `GET /profile` — user's own predictions with per-prediction breakdown.

### `admin` (`routes/admin.py`, url_prefix=`/admin`)
- `/` → redirects to `/admin/matches`
- `/matches` (list), `/matches/new`, `/matches/<id>/edit`, `/matches/<id>/delete`
- `/matches/<id>/result` — enter score + first scorer + MOTM. Sets `status='finished'`. **Does not auto-calc points** — admin must hit calculate next.
- `/matches/<id>/calc_points` — runs `score_match()`. Stamps `calculated_by_id`. Already-calculated matches reject other admins (superuser bypasses).
- `/matches/<id>/predictions` — every user's prediction on this match
- `/refresh-api` — pulls live status/scores from football-data.org via `services/api_refresh.py`
- `/users` — all users + their points (sorted: regular first, then admins, both by points)
- `/users/<id>/adjust` — set `bonus_points`
- **Superuser-only:** `/users/<id>` (full breakdown), `/points-log` (timeline)

(`fantasy-mvp` branch adds `/admin/players` and `/admin/matches/<id>/fantasy-events`, plus a whole `routes/fantasy.py` blueprint. None of that exists on `main`.)

---

## Templates

- `base.html` is the shell — nav, lang switcher (`/lang/en` or `/lang/ar`), flash messages, RTL when `is_rtl()` true.
- All admin templates live in `templates/admin/`.
- (Fantasy templates `templates/fantasy/` only exist on the `fantasy-mvp` branch.)
- Player avatar fallback pattern: `<img onerror>` swaps in a silhouette div if `photo_url` is broken.
- Flags come from `app._flag_url(team)` (Jinja global `flag_url`) — decodes the regional-indicator emoji into an ISO code and hits `flagcdn.com`.

---

## i18n

- `t('key.path')` looks up in the user's selected language (`session['lang']` ∈ {'en','ar'}, default 'en'). Falls back to the key string if missing.
- **Every user-facing string must have both `en` and `ar` translations.** When adding new keys, add to both files in the same commit.
- RTL flips automatically in `base.html` when `is_rtl()` returns True (Arabic).

---

## How data flows (typical match lifecycle)

1. Match created via `/admin/matches/new` (status='upcoming').
2. Users predict via `/match/<id>` while `is_locked()` is False.
3. Kickoff passes — predictions auto-lock.
4. Admin enters result via `/admin/matches/<id>/result` → `status='finished'`, scores stored, first scorer + MOTM stored.
5. Admin clicks "Calculate points" → `score_match()` runs → every prediction's `points_awarded` is set, `calculated_by_id` is stamped.
6. Leaderboard reflects the new points immediately (no caching).
7. `bonus_points` can be tweaked any time via `/admin/users` for manual adjustments.

---

## Seeding & data refresh

- `python scripts/seed.py` — loads teams/players/matches from `data/*.json` into the DB; creates default admin accounts (`anas` / `odai` / `ali`, password `admin123`).
- `python scripts/fetch_fifa_data.py [--skip-squads]` — pulls real WC2026 data from football-data.org (requires `FOOTBALL_DATA_API_KEY` in `.env`). Writes back into `data/*.json`. Re-seed afterwards.
- `python scripts/seed_question_bank.py` — loads the trivia pool.
- **No migration framework.** Schema changes go in `_auto_migrate()` in `app.py` as additive ALTERs. For destructive changes, delete the SQLite file and re-seed.

---

## Production (Render)

- `render.yaml` provisions a free web service + free Postgres.
- `SKIP_DB_INIT=1` is set in the runtime env to skip `db.create_all()` at gunicorn boot (cold Postgres connection can take 30–60s and times out the port scan). The build phase imports `app` indirectly via `scripts/seed.py` so the schema is set up then.
- `DATABASE_URL` is normalized from `postgres://` to `postgresql://` in `app.py`.

---

## Conventions & things to remember

- **Don't edit the README scoring table** assuming it's right — the values in `scoring.py` are authoritative (currently 3 winner / +2 exact bonus, not the old 3 exact / 1 winner-only).
- **Username = lowercase, no spaces.** Always. Login lowercases input; DB must match.
- **Predictions lock at kickoff.** Don't add UI that lets users edit after `is_locked()`.
- **`Match.first_scorer_id` and `Match.motm_id` are the prediction-game fields.** (On the `fantasy-mvp` branch they're mirrored into `MatchEvent` — don't break that sync if you ever touch the fantasy events form there.)
- **Translations go in `en.json` AND `ar.json` in the same commit.**
- **Superusers excluded from public leaderboards.** Don't accidentally include them.
- **The trivia feature was removed in `d23f6a3`** (UI and scoring both); tables `TriviaQuestion`, `TriviaAnswer`, `QuestionBank`, `MatchTrivia` are dormant. Don't add new code against them — if trivia comes back, the user will tell us how.
- **No tests run automatically** — `scripts/test_e2e.py` exists but isn't wired into CI. Verify changes manually by running `start_server.bat` and clicking through.

---

## Quick reference — common asks

| Ask | Where to look |
|---|---|
| "Why can't user X log in?" | `routes/auth.py:13` — username must be lowercase in DB |
| "Change the points for a winner pick" | `scoring.py` (`POINTS_*` constants at top) |
| "Add a column to a model" | `models.py` + add an `ALTER TABLE ADD COLUMN` in `_auto_migrate()` in `app.py` |
| "Translate a new string" | `translations/en.json` + `translations/ar.json` |
| "Bonus points for a user" | `/admin/users` → adjust |
| "Force someone to change password" | Set `User.must_change_password = True` |
| "See full point breakdown for user X" | (superuser) `/admin/users/<id>` |
| "Recompute points for a match" | `/admin/matches/<id>/calc_points` (calls `score_match`) |
| "Update live status from API" | `/admin/refresh-api` button |
| Anything about the fantasy game | switch to `fantasy-mvp` branch + read `docs/fantasy-build-log.md` |
