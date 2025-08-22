# FPL Bot Planner

A command-line assistant for Fantasy Premier League.  
It projects points, suggests transfers, flags chip opportunities, and explains *why*.  

---

## Features

✅ Per-player projections using:
- Recent points per appearance (with decay)
- Regression to position baselines
- Minutes probability model (`p60`)
- Opponent strength (home/away normalized)

✅ Transfer suggestions:
- Compares horizon gain vs hit cost
- Labels moves as `(free)` or `(uses -4 hit)`
- Shows short-term GWΔ impact separately

✅ Chip planning:
- Bench Boost signal (bench ≥ 12 xPts)
- Triple Captain signal (DGW star identified)

✅ Explainability:
- Each transfer shows: raw gain, net after hits, hit status, GWΔ
- Configurable knobs for conservatism vs aggression

---

## Installation

```bash
git clone https://github.com/YOURNAME/fpl-bot.git
cd fpl-bot
pip install -r requirements.txt
```

## Usage
Run the planner:

```bash
python3 planner.py
```

## Output includes:

- Sorted starters by projected GW points
- Bench order
- Captain suggestion
- Transfer suggestions (with gains, hits, GW deltas)

## Config
Copy config.example.yaml → config.yaml and update:

``` yaml
team_id: 41706
horizon: 3
auth_header: "Bearer eyJ..."    # copy from your browser devtools
user_agent: "Mozilla/5.0 ..."
referer: "https://fantasy.premierleague.com/my-team"
```

Knobs let you control risk appetite:

- regression_factor: blend between recent vs long-term averages
- min_baseline: per-fixture floor
- require_no_hit: block hit transfers
- gk_swap_min_gain: minimum gain to bother with backup GK
- bench_min_gain: bench upgrades threshold

## Roadmap
See ROADMAP.md for upcoming work:

- Minutes model 1.0
- Optimizer for 2FT scenarios
- Chip planner across 4–6 week horizon
- Reporting & Markdown exports
- Snapshot caching

## Example Output
```yaml
FPL Planner – Team 41706
Current GW: 2 | Horizon: 3 GWs | Bank: £0.0m | FTs: 1 | Hit: -4 per extra

Starters (sorted by GW xPts):
   Reijnders    MID £5.6  GW2: 5.24  3GW: 15.73
   Salah        MID £14.5 GW2: 4.00  3GW: 13.08
   Sánchez      GK  £5.0  GW2: 3.93  3GW: 12.25

Transfer suggestions:
  SELL  Wirtz (MID)   3GW: 6.67
  BUY   Semenyo (MID) 3GW: 21.48
  ==> Gain: +14.81 xPts | Net after hits: +14.81 (free) | GW2 Δ: +5.59
  ```

## License
MIT — feel free to hack, extend, and run your own auto-FPL bot.