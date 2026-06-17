# Fantasy Game — Build Log

**Branch:** `fantasy-mvp` (not yet merged into `main`)
**Goal:** FPL/UCL Fantasy-style game running alongside the existing prediction game for WC 2026.

> This file is the source of truth for the fantasy implementation. Future Claude sessions should **read this first** before touching any fantasy code. Update it at the end of every completed phase.

---

## Frozen rules (agreed with user, do not change without asking)

### Format
- **Path A** chosen (admin enters per-player events; not match-outcome only).
- Coexists with the current prediction game — does not replace it.
- Point values frozen as listed below.
- Squad: 15 players (2 GK / 5 DEF / 5 MID / 3 FWD), €100m budget, max 3 per country.
- Starting XI + 4 bench, valid formation (1 GK, ≥3 DEF, ≥2 MID, ≥1 FWD).
- 1 captain (×2 pts), 1 vice-captain (subs in if captain plays 0 min).

### Tournament phases (act as gameweeks)
| Phase | Free transfers before | Notes |
|---|---|---|
| Group MD1 | initial squad pick | |
| Group MD2 | 2 | |
| Group MD3 | 2 | |
| R32 | **Wildcard window** (unlimited) | |
| R16 | 3 | |
| QF | 3 | |
| SF | unlimited | |
| Final + 3rd | unlimited | |

Extra transfers cost **−4 pts each**.

### Chips (each usable once over the whole tournament)
- **Wildcard** — auto-available before R32 (unlimited transfers)
- **Limitless** — one phase, no budget cap
- **Triple Captain** — one phase, captain ×3
- **Bench Boost** — one phase, all 15 score

### Scoring (simplified Path A — no minutes/saves tracked)
| Event | GK | DEF | MID | FWD |
|---|---|---|---|---|
| Appeared in match | +1 | +1 | +1 | +1 |
| Starting XI (full 90) | +2 | +2 | +2 | +2 |
| Goal | +10 | +6 | +5 | +4 |
| Assist | +3 | +3 | +3 | +3 |
| Clean sheet | +5 | +5 | +1 | 0 |
| Every 2 goals conceded | −1 | −1 | 0 | 0 |
| Team won | +2 | +2 | +2 | +2 |
| Team drew | +1 | +1 | +1 | +1 |
| Man of the Match | +3 | +3 | +3 | +3 |
| Yellow card | −1 | −1 | −1 | −1 |
| Red card | −3 | −3 | −3 | −3 |
| Own goal | −2 | −2 | −2 | −2 |
| KO multiplier (R16+) | ×1.25 applied to total from this match |

### Player photos
- Default: **silhouette + jersey number + flag** (FPL-style fallback). 100% coverage, never broken.
- One-time Wikipedia REST API fetch will fill `players.photo_url` for ~60–70% of stars before launch.
- Admin can paste a manual URL on any player to override.

---

## Build phases

Each phase has its own section below. After completing a phase: append a summary, list every file touched, and mark the phase complete with the commit SHA (or "uncommitted on fantasy-mvp" if not yet committed).

---

## Phase 1 — Schema + Admin Event Entry  ✅ COMPLETE

**Status:** uncommitted on `fantasy-mvp` branch.
**Date:** 2026-06-16.

### Database changes

| Table | Change |
|---|---|
| `players` | Added `price NUMERIC(4,1) DEFAULT 4.0 NOT NULL` (€m, e.g. 12.5) |
| `players` | Added `photo_url VARCHAR(500) NULL` |
| `match_events` (new) | One row per (match, player) with: `started`, `came_on`, `goals` (int), `assists` (int), `own_goals` (int), `yellow` (bool), `red` (bool), `is_motm` (bool), `created_at`. Unique on `(match_id, player_id)`. |

Auto-migration handled in `app.py:_auto_migrate()` — additive ALTER TABLEs only; `match_events` created via `db.create_all()`.

### Files touched
- `models.py` — extended `Player` (price + photo_url), added `MatchEvent` model.
- `app.py` — auto-migration for new `players` columns (both Postgres and SQLite).
- `routes/admin.py` — imported `MatchEvent`; new route `match_fantasy_events` (GET/POST) at `/admin/matches/<mid>/fantasy-events`.
- `templates/admin/fantasy_events.html` — main form template.
- `templates/admin/_fe_goal_row.html` — partial used to render a single editable goal row (scorer + assister).
- `templates/admin/matches.html` — added purple "⚡ Fantasy" button in the per-match action row.
- `translations/en.json` — 17 new keys (`admin.fe_*`, `admin.fantasy_events_title`, `admin.fantasy_events_saved`, `admin.back`).
- `translations/ar.json` — Arabic translations for the same 17 keys.

### Behavior

- Admin opens any match → clicks **⚡ Fantasy** → form has, per team:
  - Starting XI checkboxes (grid of 2 columns)
  - Subs-in checkboxes
  - Yellow cards multi-select
  - Red cards multi-select
- Plus tournament-wide blocks:
  - Goals: dynamic rows of (scorer dropdown, assister dropdown). "+ Add goal" button appends a row; × removes (but never zero rows — last row is just cleared).
  - Own goals: single select (one-shot; future enhancement could allow multiple).
  - MOTM: single select across both teams; also mirrored onto `Match.motm_id` so the existing prediction game still sees it.
- Saving wipes existing `match_events` rows for the match and re-inserts (idempotent re-save).
- Form re-loads existing entries when revisited.

### Decisions worth remembering

- Goals are stored as **counts per (match, player)**, not individual goal rows with minute. Means we lose the order/minute of goals but the scoring engine doesn't need it — saves a lot of UI complexity.
- Own-goal currently single-select. If a match has 2 OGs against the same team, we can't represent it yet — extend to multi-row later if needed (unlikely in WC).
- `match.first_scorer_id` (existing prediction-game field) is **not** auto-derived from MatchEvent. The first-scorer entry in `match_result` and the goal scorers in `match_fantasy_events` are independent fields. The prediction game still uses `first_scorer_id`; the fantasy game uses `MatchEvent.goals > 0`. **If you change this, update both forms.**
- `MOTM` is double-written: into `MatchEvent.is_motm` AND `Match.motm_id`. Keeps the prediction game working unchanged.

### Translation keys added (EN/AR both have these)

```
admin.back, admin.fe_btn, admin.fantasy_events_title, admin.fantasy_events_saved,
admin.fe_starters, admin.fe_subs_in, admin.fe_yellow, admin.fe_red,
admin.fe_goals, admin.fe_add_goal, admin.fe_scorer, admin.fe_assister,
admin.fe_own_goals, admin.fe_own_goals_hint, admin.fe_motm
```

---

## Phase 2 — Player Prices + Wikipedia Photo Fetch  ✅ COMPLETE

**Status:** uncommitted on `fantasy-mvp` branch.
**Date:** 2026-06-16.

### What was built

**Admin players page** at `/admin/players?team=<team_id>`:
- Team picker dropdown (auto-submits on change).
- Table of all players for the selected team: shirt #, name (EN + AR), position, price input (€m, step 0.5, range 4–15), photo URL input, live preview avatar.
- Per-row **quick-set price buttons** (12 / 9 / 7 / 4) matching the tier system.
- Tier legend banner above the table (Superstar €12–13, Star €9–11, Regular €7–8, Role €5–6, Squad €4).
- Bulk save: changes batched into one POST; only rows whose price OR photo actually changed get committed (avoids spurious updates).

**Photo preview** in the rightmost column:
- If `photo_url` is set: shows a 40×40 rounded image.
- If not: shows a slate-300 circle with the shirt number (the FPL-style silhouette fallback). Same logic will be reused on the pitch view in phase 5.

**Wikipedia fetch script** at `scripts/fetch_player_photos.py`:
- Hits `https://en.wikipedia.org/api/rest_v1/page/summary/<title>` with a polite custom User-Agent.
- Tries title variants in order: `<Name> (footballer)` → `<Name> (soccer)` → `<Name> (<Country> footballer)` → `<Name>`.
- For the bare-name fallback, requires the page description/extract to mention a footballer keyword (defender/midfielder/etc.) to avoid grabbing an actor with the same name.
- Prefers `originalimage` over `thumbnail`; filters out obvious junk (flag SVGs, default avatars, generic soccer ball).
- Rate-limited to ~1.25 req/s via 0.8s sleep between calls.
- Defaults: skips players that already have `photo_url`, and skips placeholders whose name contains `#` (e.g. "Brazil #14").
- Flags: `--refresh` (overwrite all), `--team <code>` (e.g. `--team USA`), `--limit N` (dry-run cap).
- One-time runtime: ~20 minutes for ~1100 players. Expected ~60–70% hit rate on stars; near-zero on placeholders (correctly skipped).

### Files touched
- `routes/admin.py` — new route `fantasy_players` (GET/POST) at `/admin/players`.
- `templates/admin/players.html` — main editor template (table with inline price + photo + preview).
- `templates/admin/matches.html` — new purple **Players** button in the top action row.
- `scripts/fetch_player_photos.py` — Wikipedia photo fetcher CLI.
- `translations/en.json` + `ar.json` — 17 new keys (`admin.players_*`, `admin.player`, `admin.player_price`, `admin.player_photo`, `admin.team`, `admin.position`, `admin.preview`, `admin.tier_*`, `admin.fantasy_section`).

### Decisions worth remembering

- **Price storage:** `Numeric(4,1)` so values like `12.5` round-trip correctly. Form input uses `step=0.5`. SQLAlchemy returns `Decimal`; Jinja `'%.1f' % (p.price | float)` handles formatting safely.
- **Photo URL is just a string** — no validation beyond `type="url"` in the input. Allows manual override of any source (transfermarkt, custom CDN, etc.). Frontend will fall back to silhouette on `<img onerror>` in phase 5.
- **No tier model.** Tier is just a price band, not a stored field. The quick-set buttons are convenience only.
- **Wikipedia script doesn't run automatically.** Admin must invoke from CLI. Reason: 20-minute runtime is too long for a web request, and we want the admin to review missing photos and decide which to fill manually.
- **Placeholder players** (auto-generated like "Brazil #14") never get a Wikipedia hit — script filters them with a `LIKE %#%` exclusion to save 70% of API calls.

### How the admin uses this

1. Open `/admin/players`, pick a team → see ~23 players.
2. Click the price-preset buttons (12/9/7/4) on each row to assign tier quickly, or type a custom value.
3. Optionally paste a photo URL for known stars (e.g. transfermarkt portrait).
4. Click **Save** → all changes for that team commit at once.
5. Repeat for next team.
6. **Once per pre-tournament:** run `python scripts/fetch_player_photos.py` to fill missing photos in bulk via Wikipedia. Anything still missing keeps the silhouette card.

### Translation keys added (EN/AR both have these)

```
admin.fantasy_section, admin.players_btn, admin.players_title, admin.players_hint,
admin.players_saved, admin.team, admin.pick, admin.player, admin.position,
admin.player_price, admin.player_photo, admin.preview, admin.tier_legend,
admin.tier_superstar, admin.tier_star, admin.tier_regular, admin.tier_role,
admin.tier_squad
```

---

## Phase 3 — Squad Picker UI  ✅ COMPLETE

**Status:** uncommitted on `fantasy-mvp` branch.
**Date:** 2026-06-16.

### What was built

**Two-page user flow:**

1. **`/fantasy/pick`** — pick 15 players
   - Player browser: name search, team dropdown, position tabs (ALL/GK/DEF/MID/FWD), "show selected only" toggle
   - Sticky status bar at top with: budget bar (€ used / €100m), per-position counters (X/2, X/5, X/5, X/3), total (X/15)
   - Click a player card → adds/removes from squad
   - Client-side rule enforcement: rejects an add that would break position quota, country max (3), or budget
   - **Save button is disabled until exactly 15 picks form a valid squad**
   - Server-side validation duplicates every client check (size, position quotas, country max, budget); any violation flashes an error and re-renders the page

2. **`/fantasy/lineup`** — choose starting XI + captain/vice
   - Picks grouped by position (GK / DEF / MID / FWD)
   - Per-row: starter checkbox + two radio buttons (C = captain, V = vice)
   - Sticky status bar with starter count + per-position counts and (min–max) hints
   - Live JS validation: blocks save until 11 starters with valid formation (1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD), captain + vice both starters and distinct
   - On first save from `/fantasy/pick`, server seeds a default starting XI (4-4-2: 1 GK + 4 DEF + 4 MID + 2 FWD, picking the most-expensive per position) so users always land on a valid lineup

**`/fantasy/`** → redirects to `/pick` if no squad, else `/lineup`.

### Files touched
- `models.py` — added `FantasySquad` (user_id unique, captain_id, vice_id) and `FantasyPick` (squad_id, player_id, is_starter, slot). Unique constraint on (squad_id, player_id).
- `app.py` — registered new `routes.fantasy` blueprint.
- `routes/fantasy.py` — new module. Three routes (`home`, `pick`, `lineup`). All server-side rule constants live at the top of this file (`SQUAD_SIZE`, `POSITION_QUOTAS`, `MAX_PER_COUNTRY`, `BUDGET`, `STARTERS`, `MIN_FORMATION`, `MAX_FORMATION`).
- `templates/fantasy/pick.html` — squad picker UI with vanilla-JS state and live validation.
- `templates/fantasy/lineup.html` — starting XI + captain/vice picker.
- `templates/base.html` — added Fantasy link to desktop nav and mobile drawer (after Leaderboard, before Admin).
- `translations/en.json` + `ar.json` — 42 new keys (`fantasy.*`, `nav.fantasy`).

### Decisions worth remembering

- **No phase model yet.** Squads are global, not per-tournament-phase. The transfer/lock concept comes in phase 6. For now any user can re-save their squad at any time.
- **Placeholder players are filtered out** from the picker (`~Player.name_en.like('%#%')`) so users only see real WC2026 players. Once you finish entering real squads via the admin players page, this filter becomes a no-op.
- **Default 4-4-2 on first save.** After picking 15 players the server marks 11 as starters using a 4-4-2 picking the most-expensive per position. User can override on the lineup page.
- **Client and server validate the same rules** — pure defense-in-depth. Client gives instant feedback; server is the source of truth.
- **`selected_ids` is sent as a CSV string** in a hidden input rather than 15 separate inputs. Simpler JS state, cleaner POST.
- **Captain/vice are stored on `FantasySquad`**, not on `FantasyPick`, so they can be cleared without re-touching picks.
- **No "in this phase" concept on captain/vice yet** — they're just current values. When phase 6 introduces transfer/phase windows the lineup will be snapshotted per phase.
- **Photo fallback in JS** uses `onerror=this.replaceWith(...)` to swap to a silhouette div if the photo URL fails to load. So a broken Wikipedia URL never shows a broken image icon.

### How a user creates a squad now

1. Click **Fantasy** in the nav (next to Leaderboard) → lands on `/fantasy/pick`.
2. Filter / search players, click cards to pick 15.
3. When 15 valid picks are made, **Save squad** activates.
4. On save, server validates and redirects to `/fantasy/lineup`.
5. On the lineup page, 11 default starters are pre-selected (4-4-2). User can re-shuffle, then picks Captain (gold C) and Vice (silver V).
6. **Save lineup** persists.
7. Re-visit `/fantasy/lineup` any time to tweak; re-visit `/fantasy/pick` to fully rebuild the squad.

### Translation keys added (EN/AR both have these)

```
nav.fantasy, fantasy.section, fantasy.pick_title, fantasy.pick_hint, fantasy.budget,
fantasy.total, fantasy.search, fantasy.all_teams, fantasy.show_selected, fantasy.add,
fantasy.remove, fantasy.save_squad, fantasy.pick_15, fantasy.ready,
fantasy.err_too_many, fantasy.err_budget_short, fantasy.err_pos_full,
fantasy.err_country_full, fantasy.err_size, fantasy.err_unknown_player,
fantasy.err_position, fantasy.err_country, fantasy.err_budget, fantasy.saved,
fantasy.lineup_title, fantasy.lineup_hint, fantasy.edit_squad, fantasy.save_lineup,
fantasy.starters, fantasy.pos_gk, fantasy.pos_def, fantasy.pos_mid, fantasy.pos_fwd,
fantasy.captain, fantasy.vice, fantasy.ready_save, fantasy.err_starters,
fantasy.err_starters_short, fantasy.err_formation, fantasy.err_no_captain,
fantasy.err_no_vice, fantasy.err_captain_vice_same, fantasy.err_captain_must_start,
fantasy.lineup_saved
```

## Phase 3.5 — UX polish + bulk price seed  ✅ COMPLETE

Mid-phase fixes/additions on top of phase 3, before scoring.

**What changed:**
- **Position normalization** — `Player.fpl_position()` method on the model that maps "Goalkeeper"/"Defence"/"Midfield"/"Offence"/etc. to short codes (GK/DEF/MID/FWD). Fixed the picker filter and the "Add" button which were both silently failing because the underlying data uses full position words.
- **FPL-style pitch view** moved from phase 5 into the picker. Two-column layout (pitch left, list right). Players slot onto the correct row when added; hover a slot for the red × removal button.
- **Clear-all button** on the picker — confirm dialog, then wipes all 15 picks and resets the pitch.
- **Bulk price seed**:
  - `data/player_prices.json` — curated list of ~115 well-known WC2026 stars with fantasy prices.
  - `scripts/seed_player_prices.py` — reads the JSON, fuzzy-matches (exact normalized → last-name → token-overlap) each entry to a DB player, and updates `players.price`. Supports `--dry-run`.
  - First-run result: 85 prices applied. Unmatched names typically were just aliases for already-matched players.

**Files touched:**
- `models.py` — added `Player.fpl_position()`.
- `routes/fantasy.py` — switched all `p.position` references to `p.fpl_position()`.
- `templates/fantasy/pick.html` — full rewrite: pitch + list layout, clear-all button, JS state for pitch slots, hydration on reload.
- `templates/fantasy/lineup.html` — uses `fpl_position()` for grouping and `data-pos`.
- `translations/en.json` + `ar.json` — `fantasy.clear_all`, `fantasy.clear_confirm`.
- `data/player_prices.json` (new) — curated star list.
- `scripts/seed_player_prices.py` (new) — bulk-seeder.

## Phase 3.6 — Lineup pitch view + squad lock  ✅ COMPLETE

**Why:** make the lineup page feel like FPL, prevent the 12th-starter mistake, and apply the FPL transfer rule (no buying after the tournament starts).

### What changed
- **Lineup pitch view** — full rewrite: pitch on the left with the 11 starters arranged by formation row + a Bench panel below; squad list on the right with starter toggle (green dot) and C/V buttons.
- **Captain visuals:** gold C badge above slot, gold glow.
- **Vice visuals:** **blue** badge + blue glow (was silver — user feedback).
- **Hard block on 12th starter:** when there are already 11 starters, the green dot on non-starter rows goes grey + non-clickable. Click is intercepted with a clear "remove one first" message. Unchecking is still allowed at any time.
- **Squad lock:** new helper `is_squad_locked()` in `routes/fantasy.py` returns True once any match has kicked off. Mirrors FPL gameweek lock.
  - `/fantasy/pick` redirects to `/fantasy/lineup` with a flash when locked.
  - `/fantasy/lineup` shows a red "Squad locked — transfers closed" banner. The starter toggles + C/V remain editable (FPL allows lineup tweaks between matches in the same week).

### Files touched
- `routes/fantasy.py` — added `is_squad_locked()` + gating in `pick`; pass `squad_locked` flag to lineup template.
- `templates/fantasy/lineup.html` — pitch+bench layout, vice→blue, click-blocker on 12th starter, locked banner.
- `translations/en.json` + `ar.json` — `fantasy.bench`, `fantasy.err_swap_first`, `fantasy.locked_*`.

### Decisions worth remembering
- **Lock is global, not per-phase.** Once *any* match has started, the squad is frozen for the rest of the tournament. Proper phase-by-phase transfer windows + chip system are still Phase 6.
- **Lineup edits stay open** while the squad is locked. This matches FPL: you can rejig the starting XI and change the captain between any two matches your players appear in.
- **No transfer ledger yet.** Once we add per-phase windows, we'll need a transfer-count + −4 penalty system, plus phase snapshots so old lineups don't get overwritten.

## Phase 3.7 — Phase-based transfer windows + points-on-pitch + countdown  ✅ COMPLETE

**Why:** the user picked Option B (transfer window opens after every round), wanted points visible above each player on the pitch, and a live countdown so they always know when the window flips.

### What was built

**Transfer windows tied to tournament phases (Option B):**
- New `transfer_window_state()` in `routes/fantasy.py` returns a dict: `status`, `phase_in_play`, `next_event_at`, `next_event_type`, `next_phase`.
- Phase groupings: `group` / `r32` / `r16` / `qf` / `sf` / `final` (final pairs with third-place).
- Algorithm:
  - **Phase in play** = a phase whose first match has kicked off but not all matches are finished → window LOCKED until phase ends (`next_event_at` = last kickoff + 2h, approximation).
  - **Between phases** (or before tournament) → window OPEN, closes at next phase's first kickoff.
  - **After everything** → permanently locked.
- `is_squad_locked()` is now a thin wrapper around the state function.

**Fantasy scoring engine** (new `fantasy_scoring.py`):
- `player_match_points(player, match, event)` — pure function applying the locked rule sheet (start/sub bonus, goal/assist points by position, clean sheet, conceded penalty, win/draw, MOTM, cards, own goals, KO ×1.25 multiplier).
- `player_total_points(player_id)` — sum across all matches.
- `points_map_for_players([ids])` — bulk version for templates, single query.
- Currently returns 0 for everyone because no MatchEvent rows exist yet (admins haven't entered any). Once they do, points update live everywhere.

**Points badge above each pitch slot:**
- New `.ps-points` CSS class — green gradient pill positioned above the player's photo, showing total tournament points.
- Rendered by both `pick.html`'s `fillSlot()` and `lineup.html`'s `makeSlot()`.
- Data flows: route computes `points_map` → template emits `data-points` on each row → JS reads it when creating a slot.

**Live countdown banner:**
- Both `/fantasy/pick` and `/fantasy/lineup` render a banner at the top.
- Green when window is open ("Closes in 1d 04:23:11"), red when locked ("Opens in 02:15:48").
- JS ticks every 1s, computes `d h:m:s` until the next flip.
- Banner copy uses translation keys with phase-name interpolation (`{phase}` renders as "Round of 32", "Quarter-finals", etc.).

### Files touched
- `fantasy_scoring.py` (new) — scoring helpers.
- `routes/fantasy.py` — `transfer_window_state()`, passes `window` + `points_map` to both templates.
- `templates/fantasy/pick.html` — points badge in slot, countdown banner.
- `templates/fantasy/lineup.html` — points badge in slot, replaced static lock banner with countdown banner.
- `translations/en.json` + `ar.json` — 14 new keys (`fantasy.locked_phase`, `fantasy.window_open`, `fantasy.opens_in`, `fantasy.closes_in`, `fantasy.phase_*`).

### Decisions worth remembering
- **Phase grouping `final` includes both `third` and `final`** — they're played in the same window so they share one phase.
- **"Phase ended" = 2 hours after last kickoff.** Rough approximation that avoids parsing the actual final whistle. Refine later if needed.
- **Points are computed on every page load.** No caching yet. Fine while volume is small; consider memoizing or denormalizing if it gets slow.
- **`data-points` is server-rendered on each row.** When the admin enters events, the next page load shows fresh totals. No background refresh.
- **`next_event_at` is naive UTC datetime** (from `Match.kickoff_utc`). Templates append `Z` so JS parses it as UTC. If you ever store kickoffs with tz info this stays correct.

## Phase 4 — Fantasy Leaderboard + Breakdown  ✅ COMPLETE

**Status:** uncommitted on `fantasy-mvp` branch.
**Date:** 2026-06-16.

### What was built

**User-level scoring helpers** (added to `fantasy_scoring.py`):
- `user_fantasy_breakdown(squad)` — returns `{rows, starters_total, captain_bonus, total}`. Each row in `rows` has `player`, `is_starter`, `is_captain`, `is_vice`, `raw_points`, `captain_bonus`, `effective_points`. Sorted: starters first (by effective_pts desc), then bench.
- `user_fantasy_total(squad)` — thin wrapper returning just the integer total.
- **Captain bonus** = one extra copy of the captain's raw points (because ×2 = raw + one bonus copy). Stored separately so the breakdown can show "From starters: 87 / Captain bonus: +12".
- Bench rows are returned with `effective_points = 0` so they show for context but don't contribute.

**New routes** in `routes/fantasy.py`:
- `GET /fantasy/leaderboard` — ranked list of every `FantasySquad` (excluding superusers, matching main leaderboard convention). Each row clickable → goes to `/fantasy/breakdown/<user_id>`.
- `GET /fantasy/breakdown` / `GET /fantasy/breakdown/<user_id>` — full table for one user. Defaults to the current user; admins can pass any `user_id`; non-admins viewing someone else get a 403.

**Templates:**
- `templates/fantasy/leaderboard.html` — top-3 podium (🥇🥈🥉) above a ranked table with rank badge, username, captain name, total points. Click-through to breakdown.
- `templates/fantasy/breakdown.html` — three stat cards (Total / From starters / Captain bonus) + per-player table with C/V pills, photo, country, position pill, raw / captain bonus / effective columns.

**Nav wiring:**
- `🏆 Fantasy leaderboard` button on both `/fantasy/pick` and `/fantasy/lineup`.
- Translations include `fantasy.leaderboard_title`, `fantasy.total_pts`, `fantasy.from_starters`, `fantasy.captain_bonus`, `fantasy.raw_pts`, `fantasy.captain_bonus_col`, `fantasy.effective_pts`, `fantasy.breakdown_hint`, `fantasy.no_squads_yet`, etc.

### Files touched
- `fantasy_scoring.py` — appended `user_fantasy_breakdown()` + `user_fantasy_total()`.
- `routes/fantasy.py` — added `leaderboard` and `breakdown` routes.
- `templates/fantasy/leaderboard.html` (new) — podium + ranked table.
- `templates/fantasy/breakdown.html` (new) — per-user breakdown.
- `templates/fantasy/pick.html` + `lineup.html` — added Leaderboard button.
- `translations/en.json` + `ar.json` — 15 new keys.

### Decisions worth remembering

- **Current lineup applies to all historical matches.** We don't snapshot the lineup per phase yet (that's phase 6). So if a user changed their captain mid-tournament, their entire history reflects the *current* captain, not the historical one. Acceptable while the tournament hasn't run.
- **Superusers are excluded from the fantasy leaderboard** to match the main leaderboard's rule.
- **Admins can view any user's breakdown** (via `/fantasy/breakdown/<id>`); regular users see their own only.
- **Page-load scoring is O(squads × picks × events)** — fine for ~50 squads × 15 picks × few matches. If it ever feels slow, denormalize a `FantasyPick.points_cached` column.
- **Click-row interaction** on the leaderboard mirrors the FPL "view team" pattern.

## Phase 5 — FPL-style pitch view  ✅ ALREADY DONE in phase 3.5
*(Pitch view was pulled forward into the picker + lineup pages.)*

## Phase 6 — Per-phase transfer ledger + chips  (PLANNED)
- Snapshot the lineup + captain at the moment each phase locks, so the leaderboard reflects what the user actually fielded each round.
- Add chips: Wildcard, Limitless, Triple Captain, Bench Boost (used once each).
- Track free-transfer count between phases and apply −4 pts for extras.
## Phase 5 — FPL-style Pitch View  (PLANNED)
## Phase 6 — Transfer Windows + Chips  (PLANNED)

---

## Open questions / future considerations

- **Phases as a concept** — currently no `Phase` model. We're keying off `Match.stage` (group/r32/r16/...) and we'll need to introduce a phase concept that groups MD1/MD2/MD3 separately for the group stage. Will be added in phase 3 or 4.
- **Squad lock time** — likely the kickoff of the first match of the phase. Will need a `phase_lock_at` field on a future `Phase` table.
- **Transfer accounting** — each squad needs a transfer ledger so we can charge −4 for excess transfers.
- **Fantasy users vs prediction users** — same `users` table; participation is implicit (a user with a `FantasySquad` row is in the fantasy game).
