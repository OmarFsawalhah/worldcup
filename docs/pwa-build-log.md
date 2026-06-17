# PWA + Telegram Notifications — Build Log

**Branch:** `pwa-mvp` (forked from `main`).
**Goal:** users install the WC2026 predictor on their phone home screens (PWA) and receive 4 well-scoped notifications via a Telegram bot.

> This file is the source of truth for the PWA + notifications work. Future Claude sessions should **read this first** before touching the manifest, service worker, Telegram code, or notification scheduler.

---

## Frozen design decisions

### Install
- **Progressive Web App** (PWA), not a wrapped native app.
- Install on Android via the browser's "Install app" banner.
- Install on iOS 16.4+ via Share → Add to Home Screen.
- App opens full-screen (no browser UI), shows our gold "26" icon, brand-coloured splash.

### Notification channel
- **Telegram bot**, not Web Push.
- Reasoning: Telegram works on every device with no iOS-16.4 quirks, no VAPID, no service-worker push handler. Users link their account with `/start <code>` once.
- A user without Telegram still uses the app normally — they just don't get pings.

### Notifications shipped (only these 4)
1. **T-1h before kickoff** — per match, sent once. "Last hour to predict {Home} vs {Away}".
2. **Match scored** — per (user, match) when Calc Points runs. "{Home} {h}–{a} {Away} · You earned {N} pts".
3. **Round closed** — per (user, round) when the last match of a round is scored. "Group MD2 done — you're #{rank} with {pts} pts".
4. **Manual bonus** — per (user) when admin saves `bonus_points`. "{Admin} gave you +{N} bonus points".

### Things explicitly NOT shipping
- "Another user just predicted" — too noisy
- "Match has started" — adds nothing
- Live score updates per goal — would need real-time API
- Email fallback — out of scope

---

## Build phases

### Phase 1 — PWA install (no notifications yet)
- `static/manifest.webmanifest`: name, theme, icons.
- `static/sw.js`: minimal service worker (cache-first for static assets, network for everything else; no push yet).
- `static/icons/`: 192×192 and 512×512 PNG icons + apple-touch-icon. SVG fallback in manifest.
- `templates/base.html`: link to manifest, register service worker, add Apple-specific meta tags.

**Acceptance:** Chrome on Android shows "Install app" prompt; the installed shortcut opens full-screen with our icon. iOS users can add to home screen and the app opens full-screen.

### Phase 2 — Telegram bot scaffolding
- `python-telegram-bot` added to requirements.
- New model: `TelegramLink` (user_id, chat_id, linked_at).
- New route: `/profile/notifications` — shows the link status. If unlinked, displays a 6-digit code + a "Open Telegram" button that deep-links to `t.me/<bot>?start=<code>` so the bot can claim the user.
- Bot lives in `services/telegram_bot.py`. Runs in long-polling mode as a separate process (Render: background worker). On `/start <code>`, looks up the pending link, stamps `chat_id`.

**Required from user:** bot username + `TELEGRAM_BOT_TOKEN` (created via @BotFather). I'll prompt for this before phase 2.

### Phase 3 — Notification triggers
- New module `services/notifications.py` with one function per type:
  - `notify_match_starting(match)` — finds users who haven't predicted, sends T-1h alert.
  - `notify_match_scored(prediction)` — called from `score_match()` for every prediction.
  - `notify_round_closed(stage)` — called when last match of a stage is finalized.
  - `notify_manual_bonus(user, delta, admin)` — called from `/admin/users/<id>/adjust`.
- All wrapped in try/except — a notification failure never blocks the admin action.
- Throttled: each (user, type, target_id) is recorded in a `NotificationLog` table to prevent duplicates.

### Phase 4 — Scheduler for T-1h pings
- Cron-style background job. Two options:
  - A: APScheduler embedded in the web process (simplest, but lost on free Render restarts every ~15 min).
  - B: Render Cron Job firing a POST to `/admin/internal/check-pings` every 10 min.
- Going with **B** — Render handles the schedule, our endpoint is idempotent (uses NotificationLog).
- Endpoint walks every upcoming match where `kickoff_utc` is in [now+50min, now+70min] and not yet pinged, fires `notify_match_starting`.

### Phase 5 — Polish + rules update
- Profile page section explaining how notifications work + "Unlink Telegram" button.
- Translation keys for all bot messages (EN + AR).
- Docs/rules update mentioning the install steps and bot link.

---

## Files this branch will touch (live tracking)

(Will update as I build.)

- `static/manifest.webmanifest` (new)
- `static/sw.js` (new)
- `static/icons/` (new — 192/512 PNG + maskable + apple-touch)
- `templates/base.html` (link + register)
- `models.py` (+ TelegramLink, + NotificationLog)
- `app.py` (auto-migrate new tables)
- `routes/public.py` (+ notifications settings page)
- `routes/admin.py` (+ internal check-pings endpoint)
- `services/telegram_bot.py` (new)
- `services/notifications.py` (new)
- `scoring.py` (hook into `score_match` to fire notify_match_scored / notify_round_closed)
- `requirements.txt` (+ python-telegram-bot)
- `render.yaml` (+ background worker for the bot, + cron for pings)
- `translations/{en,ar}.json`
