# WC2026 Predictor — Session Handoff (compact)

> **Read first** in a fresh session, then read `docs/project-overview.md` and `docs/pwa-build-log.md` before touching the relevant code.
> Last updated: 2026-07-04 (post-session summary of everything done).

---

## 1. TL;DR — what this project is

A bilingual (EN/AR, RTL) Flask app where ~4 friends predict every 2026 FIFA World Cup match and compete on a points leaderboard.

- **Stack:** Flask + Flask-Login + Flask-SQLAlchemy · SQLite locally / Postgres on Render · Jinja + Tailwind CDN · vanilla JS
- **Entry point:** `app.py` → `create_app()` registers blueprints `auth`, `public`, `admin`
- **Default admins (must change pwd on first login):** `anas`, `ali`, `ahmad_okour` (pwd `admin123`); superuser `superuser` (pwd `super123`)
- **Run locally:** double-click `seed_database.bat` then `start_server.bat` → http://localhost:5000
- **Deploy:** push to GitHub → Render Blueprint (free plan) — `render.yaml` provisions web + free Postgres

---

## 2. Branch state (today, 2026-07-04)

| Branch | What's there |
|---|---|
| `main` (current, clean) | Core prediction game, PWA install, in-app notifications, **Web Push phone notifications** (Phase 4), superuser admin tools |
| `fantasy-mvp` | FPL-style squad game on top of same data — see `docs/fantasy-build-log.md` (not merged) |
| `pwa-mvp` | Merged into main; can delete or leave as historical |
| `ui-redesign-experiment` | Experimental UI — not merged |

Recent commits on `main` (newest first):
- `b9cf4e7` Superuser panel: manage admins + edit any user's prediction
- `4d3b31b` Use correct username 'ahmad_okour' (with underscore)
- `0f17912` Replace admin 'odai' with 'ahmadokour'
- `6fef8fd` Move winner_team_id migration to seed.py (after seed_teams)
- `c4151d7` Make knockout seeder non-fatal: skip cleanly on network error
- `c82281b` Fix: exact-score bonus pays out even on pure draws
- `06fe51f` Remove draw option + add penalty-shootout winner detection
- `c7fd9e2` Auto-seed knockout matches on every Render deploy (free-plan friendly)
- `e85383a` Add knockout-match seeder + 16 R32 fixtures
- `ad453d4` Fix RTL score-display bug — '1-3' looking like Jordan won 3-1
- `ba39636` Push enable button: better diagnostics + SW-ready timeout
- `05e24d4` PWA: notification ding (open app) + install banner
- `6d8074a` PWA phase 4: Web Push (phone-tray notifications)
- `904bf54` Update docs: project-overview + pwa-build-log reflect deployed state
- `bf5a4fd` Move bell next to language toggle (mobile + desktop)
- `87ab7c4` PWA phase 2: in-app notifications (no Telegram)
- `39ee271` PWA phase 1: installable web app

---

## 3. Scoring rules (LOCKED — code is source of truth, README is wrong)

Implemented in `scoring.py`:

| Hit | Points |
|---|---|
| Correct winner / draw | +3 (`POINTS_WINNER`) |
| Exact score (on top of winner OR pure draw like 1-1, 0-0) | +2 (`POINTS_EXACT_BONUS`) |
| First goal scorer | +3 |
| Man of the match | +3 |
| ~~Trivia answer~~ | removed in `d23f6a3` — tables dormant, don't add code against them |
| Manual admin bonus | `User.bonus_points` (free int) |

Leaderboard tie-break: exact-score hits desc, then earliest signup. **Superusers hidden from leaderboard.**

---

## 4. Domain model (active on `main`)

`models.py` — these are live:
- `User` (is_admin, **is_superuser**, must_change_password, bonus_points)
- `Team`, `Player`, `Match` (incl. `calculated_by_id`, `winner_team_id` for penalty shootouts)
- `Prediction` (winner_prediction ∈ {home, away, NULL — "draw" removed in `06fe51f`; old rows with 'draw' still in DB but earn no winner points)
- `Notification` (in-app bell + history)
- `PushSubscription` (Web Push phone notifications)

Dormant — kept for legacy data, **don't add new code against them**:
- `TriviaQuestion`, `TriviaAnswer`, `QuestionBank`, `MatchTrivia`

### Key quirks
- **Username = lowercase, no spaces.** Login does `username.strip().lower()` before lookup (`routes/auth.py:13`).
- **`kickoff_utc` is naive UTC.** Use `Match.kickoff_aware()` for tz-aware comparisons.
- **`Match.is_locked()`** = `utcnow() >= kickoff_aware()`. Predictions can't be edited after that.
- **Auto-migration** is additive `ALTER TABLE` only (`_auto_migrate()` in `app.py`). No Alembic. `winner_team_id` is added in `scripts/seed.py:_ensure_schema()` AFTER `seed_teams()` so the FK target exists.
- **Predictions unique on (user_id, match_id)** — `Prediction` has unique constraint.

---

## 5. Routes (current state)

### `auth` (`routes/auth.py`)
`/login`, `/register` (open, no admin gate), `/logout`, `/change-password`

### `public` (`routes/public.py`)
- `GET /` → dashboard (groups matches by stage + group letter; fires lazy `fire_starting_match_reminders`)
- `GET/POST /match/<id>` — wizard saves `winner_prediction` (no draw option), score, first scorer, MOTM
- `GET /leaderboard` — excludes superusers
- `GET /profile` — own predictions with breakdown
- `/notifications`, `/notifications/unread_count`, `/notifications/<id>/read`, `/notifications/mark_all_read`
- `/push/vapid-key`, `/push/subscribe`, `/push/unsubscribe`, `/push/test`

### `admin` (`routes/admin.py`, prefix `/admin`)
- `/matches` (list), `/matches/new`, `/matches/<id>/edit`, `/matches/<id>/delete`
- `/matches/<id>/result` — enter score/first scorer/MOTM; sets `status='finished'`; does NOT auto-calc
- `/matches/<id>/calc_points` — runs `score_match()`; first calc admin recorded in `calculated_by_id`; only that admin or a superuser can recalc
- `/matches/<id>/predictions` — see all predictions on a match
- `/refresh-api` — pull live status from football-data.org
- `/users` — list users + points (sorted: regular first, then admins)
- `/users/<id>/adjust` — set `bonus_points` (fires `notify_manual_bonus` if delta ≠ 0)

**Superuser-only:**
- `/users/<id>` — full prediction breakdown
- `/points-log` — chronological timeline
- `/manage-admins` — toggle `is_admin` for any user (superuser account protected from demotion)
- `/edit-prediction` — backfill/edit any user's prediction (even on locked/finished matches); optional rescore

---

## 6. PWA + Notifications — what's actually live

### PWA install (Phase 1 ✅)
- `static/manifest.webmanifest`, `static/sw.js`, `static/icons/{192,512,512-maskable,180}.png`
- Apple meta + SW register in `templates/base.html`
- Install flow: Android Chrome → ⋮ → Install; iOS 16.4+ → Share → Add to Home Screen

### In-app notifications (Phase 2-3 ✅)
- Bell icon next to EN/AR language toggle in nav (mobile + desktop)
- Polls `/notifications/unread_count` every 30s + on focus
- Four kinds fired:
  1. `match_starting` — T-1h reminder (lazy from dashboard; idempotent via unique `(user_id, kind, target_id)`)
  2. `match_scored` — after admin runs Calc Points (one per user who predicted)
  3. `round_closed` — last match of a stage finishes calc (one per non-superuser with their rank + points)
  4. `manual_bonus` — admin sets/changes bonus_points (delta-based)
- All triggers wrapped in try/except — never block the admin action

### Web Push (Phase 4 ✅ deployed, needs VAPID keys for prod)
- Every in-app notification ALSO fires a Web Push to all of the user's subscribed devices
- Service worker (`static/sw.js`, cache `wc2026-shell-v2`) handles `push` + `notificationclick`
- `/notifications` page has an "Enable phone notifications" panel
- Env vars required: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIM_EMAIL`
  - Generate locally: `python scripts/generate_vapid_keys.py`
  - Paste into `.env` for dev, Render dashboard for prod (use different key pair)
  - If env vars missing, button shows "Push isn't configured on the server yet — ask the admin"
- **Caveats:** iPhone needs iOS 16.4+ AND PWA installed via Add to Home Screen; Android works on all modern Chrome; OS tray shows English body (phone OS doesn't know app lang)

---

## 7. Render deployment notes

- **Build:** `pip install -r requirements.txt && python scripts/seed.py && python scripts/seed_knockout_matches.py`
- **Start:** `gunicorn app:app`
- **Free Postgres** with cold-start latency → `SKIP_DB_INIT=1` in runtime env (schema built during build phase)
- `DATABASE_URL` is normalized from `postgres://` to `postgresql://` in `app.py`
- `FOOTBALL_DATA_API_KEY` set as `sync: false` (set manually in Render dashboard)
- VAPID keys are `sync: false` — set in dashboard after running `generate_vapid_keys.py`

---

## 8. Recent session work (the "what just happened")

The most recent session added the superuser panel (`b9cf4e7`):
1. **`/admin/manage-admins`** — superuser can toggle `is_admin` flag for any user (except `superuser` account itself and current user, to prevent self-demotion)
2. **`/admin/edit-prediction`** — superuser can backfill/edit any user's prediction on any match (works on locked/finished matches). Optional rescore after save.
3. **Template `admin/manage_admins.html`** + **template `admin/edit_prediction.html`**
4. **`notify_manual_bonus`** documentation noted it creates a fresh notification each adjustment (delta ≠ 0, `target_id=NULL` so no idempotency constraint kicks in) — this is intentional.

Admin list now shows: `anas`, `ali`, `ahmad_okour` (replaced `odai` and removed `mohammad_hariri`).

---

## 9. Known issues / gotchas

1. **`fetch_fifa_data.py` doesn't yet have a `--update-status-only` flag** — to update live match status (UPCOMING → LIVE → FINISHED), re-run full reseed or use the admin's "Refresh API" button.
2. **Knockout matches beyond R32** may have `home_team_id`/`away_team_id` as placeholders — admin must edit via match edit form to point at real qualifying teams after the group stage. `seed_knockout_matches.py` is non-fatal on network error and will backfill on next successful run.
3. **Trivia feature is dormant** (removed in `d23f6a3`). Tables exist but no UI/scoring wires to them. **Don't add code against them** without confirming with the user — if trivia returns, the user will say how.
4. **Draw option removed from UI** in `06fe51f`. Old `winner_prediction='draw'` rows still in DB earn 0 winner points; they can still get exact-score bonus for pure draws (1-1, 0-0, etc.).
5. **No tests run automatically** — `scripts/test_e2e.py` exists but isn't wired into CI. Verify manually via `start_server.bat`.
6. **`_auto_migrate()` runs only when `SKIP_DB_INIT` is NOT set.** Render production skips it; new columns must be added via `scripts/seed.py:_ensure_schema()` (post-`create_all()`).
7. **Translations must go in BOTH `translations/en.json` and `translations/ar.json`** in the same commit.
8. **Push sends English body** — the OS notification tray doesn't know which language the user picked in the app.

---

## 10. Files map — where to look for what

| If you need to... | Look at |
|---|---|
| Change points values | `scoring.py` (constants at top) |
| Add a model column | `models.py` + `app.py:_auto_migrate()` (and/or `scripts/seed.py:_ensure_schema()` if FK dependency) |
| Add a route | `routes/auth.py` / `public.py` / `admin.py` |
| Change scoring behaviour | `scoring.py:score_match` (one source of truth, safe to re-run) |
| Add a notification kind | `services/notifications.py` + unique constraint on (user_id, kind, target_id) for idempotency |
| Add Web Push triggers | `services/notifications.py:_safe_add` already fires push; just create a Notification row |
| Modify the bell/notifications page | `templates/base.html` + `templates/notifications.html` |
| Change admin layout/templates | `templates/admin/*.html` |
| Add i18n string | `translations/en.json` AND `ar.json` |
| Update live match data | `/admin/refresh-api` (one-shot) or re-run `scripts/fetch_fifa_data.py` (full reseed) |
| Recompute points | `/admin/matches/<id>/calc_points` |
| Force password change | Set `User.must_change_password = True` |
| Tweak the leaderboard | `routes/public.py:leaderboard` (exclude superusers!) |
| Backfill a user's prediction | `/admin/edit-prediction` (superuser) |
| See a user's full breakdown | `/admin/users/<id>` (superuser) |
| See points timeline | `/admin/points-log` (superuser) |
| Add/remove an admin | `/admin/manage-admins` (superuser) |

---

## 11. Where to start a new session

1. Read this file.
2. Read `docs/project-overview.md` (non-fantasy core source of truth).
3. Read `docs/pwa-build-log.md` ONLY if touching manifest/sw.js/push/bell.
4. Read `docs/fantasy-build-log.md` ONLY if on `fantasy-mvp` branch and touching fantasy code.
5. Check `git log --oneline -10` on `main` for the most recent context.
6. If you changed any of the core constants (admin list, scoring points, blueprints), update the docs in the same commit.

---

## 12. Quick environment recap

- **OS:** Windows 11 (PowerShell primary, bash for POSIX scripts)
- **Python:** 3.11+ (3.11.9 pinned on Render)
- **Local DB:** `worldcup.db` (SQLite, gitignored via `.gitignore`)
- **Prod DB:** Postgres (free Render plan, `DATABASE_URL` from `worldcup-db` resource)
- **Football-data API:** https://www.football-data.org (free, 10 req/min, `FOOTBALL_DATA_API_KEY`)

That's the project. Come back anytime and pick up from here.