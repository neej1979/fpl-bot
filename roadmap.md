# FPL Bot — Roadmap

This roadmap turns the current planner/advisor into a reliable, data-driven assistant (and sets the stage for optional “autopilot” later). It’s organized in phases you can tackle one by one. Each item has clear deliverables and acceptance criteria.

## Phase 0 — Stabilize & Explain (now)

### Goals

Keep outputs sane week-to-week and make recommendations understandable.

### Tasks

✅ Config-first knobs (already): REGRESSION_FACTOR, MIN_BASELINE, MIN_NET_GAIN, REQUIRE_NO_HIT, GK_SWAP_MIN_GAIN.

✅ Hit/Free labeling in transfer printout; show GWΔ (short-term) vs horizon.

✅ Pre-deadline fallback to /my-team/ when /picks/ 401s.

### Deliverables

Deterministic run using the same snapshot/auth.

Transfer lines show: raw gain, net after hits, (free)/(uses -4 hit), and GW{n} Δ.

### Acceptance

If REQUIRE_NO_HIT=true, no hit moves appear.

If buy’s GWΔ < 0 and net gain < threshold, it’s flagged as short-term down/long-term up.

## Phase 1 — Projection Quality

### Goals

Improve xPts by modeling minutes and fixture strength better.

### Tasks

Minutes model 1.0

Features: last 6 match minutes, starts vs sub, injury/doubt status, red/yellow flags.

Output: p60 = probability of 60+ mins. Use xPts *= p60 (bench points largely irrelevant).

Config: minutes_window, p60_floor, p60_injury_penalty.

Fixture strength 2.0

Replace coarse difficulties with normalized opponent strength:

Option A: from bootstrap.teams strengths (current).

Option B (better): pull rolling xG for/against or public ELO/SPI (optional later).

Position-aware: attackers use opponent DEF strength; GK/DEF use opponent ATT strength.

Form regression 2.0

Bayesian blend: regress recent points per appearance to position + price-tier priors.

Config: regression_factor_by_pos, tier_priors.

### Deliverables

A pure function project_player_points_by_gw(...) with:

base = blend(recent_rppa, prior_by_pos_tier),

xPts_gw = base * p60 * fixture_scalar.

### Acceptance

Early season: projections don’t spike on 1-week wonders.

Known nailed premiums show stable 5–7 xPts, fodder ~1–2.

## Phase 2 — Better Planner / Optimizer

### Goals

Choose stronger combinations of moves under constraints.

### Tasks

Two-move search (beam or ILP)

Variables: which player to sell/buy (per position).

Constraints: budget, 3-per-club, positions, number of transfers (1 FT + optional hits).

Objective: maximize sum(horizon_xPts) – 4*hits.

### Policy gates

Stricter defaults by position:

DEF/GK hit threshold higher (e.g., min_net_gain_defgk).

MID/FWD lower threshold (carry more upside).

Bench upgrades require big horizon gain (e.g., bench_min_gain=8).

### Scenario engine

CLI/config to lock/avoid:

lock_players, avoid_players, avoid_clubs.

--what-if mode runs N scenarios and prints top-3 plans.

### Deliverables

New module optimizer.py (beam or pulp/ortools) called from planner.py.

### Acceptance

With 2FT weeks, optimizer surfaces combos that a greedy “worst-in-slot” misses.

Respect for budget and club limits is guaranteed.

## Phase 3 — Chips Planner

### Goals

Provide signal on when Bench Boost / Triple Captain / Wildcard are +EV.

### Tasks

Compute baseline vs chip scenarios over a rolling 4–6 GW window.

Add chip_planner.py (or embed in planner) to print candidate weeks with estimated EV.

Config: chip_min_ev, chip_horizon, chip_blacklist_weeks.

### Deliverables

“Chip planning signals” section lists candidate GWs and rough EV.

### Acceptance

Chips are suggested only when EV exceeds config threshold and constraints (bench depth for BB, DGW for TC) are met.

## Phase 4 — Explainability & Reporting

### Goals

Make the “why” obvious and persist outputs for review.

### Tasks

Per-player explanation card (used internally for printing):

p60, minutes window sample, fixture scalars per GW, baseline vs regressed base.

Transfer rationale:

“Semenyo > Wirtz: +5.6 now (weaker opp), +9.2 next two; minutes 75% vs 62%.”

Export:

reports/{YYYY-MM-DD}_team-{id}.md (pretty), plus CSV for xPts and transfers.

### Deliverables

Markdown + CSV after each run.

### Acceptance

A human can read the report and understand trade-offs in 30 seconds.

## Phase 5 — Data Plumbing & Stability

### Goals

Robustness to API hiccups; deterministic retries.

### Tasks

Snapshot cache 2.0: save bootstrap, fixtures, and element-summary/* per run under snapshots/DATE/.

Auth preflight: call /api/me/ (or cheap endpoint) and print [auth OK] / [auth FAIL].

Price-change watch (optional): add nightly warning if likely rises/falls.

### Deliverables

--use-snapshot snapshots/DATE to replay a run.

### Acceptance

Re-running with the same snapshot yields identical outputs.

## Phase 6 — Testing & Quality

### Goals

Avoid regressions while we iterate quickly.

### Tasks

Unit tests (deterministic fixtures):

fixture_strength_scalar (home/away & pos),

minutes_p60 logic (injury/doubt flags, starts/subs),

project_player_points_by_gw (toy histories),

propose_transfers/optimizer constraints (budget, club cap, hit ordering).

Golden tests:

Freeze snapshot + config; assert top captain and first transfer set.

### Deliverables

tests/ with a small synthetic dataset.

### Acceptance

CI (GitHub Actions) runs tests on PR; failures block merges.

## Phase 7 — UX & CLI Polish

### Goals

Make it easy to tweak without editing code.

### Tasks

Ensure all knobs live in config.yaml (no inline duplicates).

CLI overrides for key knobs (e.g., --require-no-hit, --min-net-gain 3).

Helpful errors (auth tips, missing config keys).

### Deliverables

Updated readme.md with example configs and common recipes.

### Acceptance

A new user can copy config.example.yaml, fill team id + auth, and get results in <5 minutes.

## Phase 8 — (Optional) Autopilot Prep

### Goals

Safely move toward execution (manual confirmation first).

### Tasks

Dry-run POST to FPL endpoints with no side effects; log payloads and planned changes.

“Confirm in terminal” step before any real action.

Deadline guard: refuse to act if within X minutes of deadline unless --force.

### Deliverables

executor.py with dry-run and safety rails.

### Acceptance

Dry-run produces accurate payloads matching the printed plan; never acts without explicit confirmation.

## Repo Structure (expected)
fpl-bot/
├─ advisor.py
├─ planner.py
├─ optimizer.py            # Phase 2
├─ executor.py             # Phase 8 (optional)
├─ fpl_client.py
├─ config.yaml
├─ readme.md
├─ ROADMAP.md
├─ reports/                # Phase 4
├─ snapshots/              # Phase 5
├─ tests/                  # Phase 6
└─ requirements.txt

## Config Keys (extend over time)
team_id: xxxxx
horizon: 3
snapshot_dir: null

## auth
auth_header: "Bearer ..."
user_agent: "Mozilla/5.0 ..."
referer: "https://fantasy.premierleague.com/my-team"

## projection knobs
regression_factor: 0.5
min_baseline: 2.0
minutes_window: 6
p60_floor: 0.4

## planner knobs
free_transfers: 1
hit_penalty: 4
shortlist: 80
require_no_hit: false
min_net_gain: 0.5
gk_swap_min_gain: 8.0
bench_min_gain: 8.0
min_net_gain_defgk: 4.0
min_net_gain_midfwd: 2.0

## optional policies
lock_players: []
avoid_players: []
avoid_clubs: []

## Working Style

Create a branch per phase (e.g., feat/minutes-model), open a PR.

Add/adjust tests, update readme.md if user-visible changes occur.

Merge once acceptance criteria pass on snapshots.

## Next 2 Sprints

### Sprint A (1–2 days)

Minutes model 1.0

Fixture scalar 2.0 (better clamps + team strengths)

Reporting: markdown export

### Sprint B (2–3 days)

Two-move optimizer (beam or ILP)

Scenario flags (lock/avoid)

Golden test with a frozen snapshot