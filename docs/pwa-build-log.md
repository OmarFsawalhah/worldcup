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
- **In-app only.** Bell icon in the nav with an unread count, plus a `/notifications` history page. No Telegram, no Web Push, no external dependency.
- Reasoning: works for every user on every device, no setup. The PWA install makes opening the app a one-tap action, so missing a notification just means "you'll see it next time you open the app" — fine for a small friends group.
- *(Pivoted from Telegram. The user doesn't have Telegram even though their friends do, and in-app is simpler. Web Push remains a future option if anyone wants notifications when the app is closed.)*

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

### Phase 2 — In-app notifications (schema + service + triggers)
- New model `Notification`: id, user_id, kind, message_en, message_ar, link_url, is_read, created_at. Each user has their own row per event.
- New module `services/notifications.py` with one function per kind:
  - `notify_match_scored(prediction, match)` — called from `score_match()` per prediction.
  - `notify_round_closed(stage)` — called when the last match of a stage finishes calc.
  - `notify_manual_bonus(user, delta, admin)` — called from `/admin/users/<id>/adjust`.
  - `notify_match_starting(user, match)` — triggered lazily on dashboard load for matches in [now+50min, now+70min] that the user hasn't been notified about and hasn't predicted.
- All triggers wrapped in try/except — never block the admin action.
- Idempotency: `Notification` has a unique constraint on `(user_id, kind, target_id)` so re-firing the same event doesn't create duplicates.

### Phase 3 — UI: bell + notifications page
- Bell icon in the nav (between Leaderboard and Profile) with a red unread-count badge.
- `/notifications` page showing the user's history, newest first, with "Mark all read" button.
- Click a notification → marks it read and navigates to `link_url` (if any).
- Tiny JS in `base.html` polling `/notifications/unread_count` every 30 seconds while the page is open, updating the badge live.

### Phase 4 — Polish + rules update
- Profile page section explaining what notifications appear.
- Translation keys for all message types (EN + AR).
- Docs/rules update.

### Future (NOT in this branch)
- Web Push notifications — true push when the app is closed. Requires VAPID keys, a push library, and a fresh permission flow. Only adds value for the "app is closed" use case.

---

## Files this branch will touch (live tracking)

(Will update as I build.)

- `static/manifest.webmanifest` (new) — done phase 1
- `static/sw.js` (new) — done phase 1
- `static/icons/` (new) — done phase 1
- `templates/base.html` (manifest link + SW register done; bell icon coming)
- `models.py` (+ Notification table)
- `app.py` (auto-migrate the new table)
- `services/notifications.py` (new — 4 trigger functions)
- `routes/public.py` (+ /notifications page + /notifications/unread_count endpoint + lazy match-starting trigger on dashboard)
- `routes/admin.py` (+ hook into user_adjust → notify_manual_bonus)
- `scoring.py` (+ hook into score_match → notify_match_scored + notify_round_closed)
- `translations/{en,ar}.json`
