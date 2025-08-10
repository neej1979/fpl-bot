# FPL Bot Lite

A data-driven assistant for [Fantasy Premier League](https://fantasy.premierleague.com/).  
Makes transfer, captaincy, and squad recommendations based on fixtures, form, and odds.

## Features
- Reads live or snapshot FPL API data
- Suggests captain, vice, bench order
- Transfer suggestions with net expected points gain
- Demo snapshot mode for pre-season

## Quickstart
```bash
git clone https://github.com/YOUR-USER/fpl-bot.git
cd fpl-bot
pip install -r requirements.txt

# Run advisor (snapshot mode)
python3 fpl_bot/advisor.py --team-id 41706 --horizon 3 --snapshot-dir snapshot_demo

# Run planner
python3 fpl_bot/planner.py --team-id 41706 --horizon 3 --free-transfers 1 --hit-penalty 4 --snapshot-dir snapshot_demo
Roadmap
Odds-based projections

Multi-GW chip planning

ILP-based optimizer

yaml
Copy
Edit

---

## **Initialise + push to GitHub**
```bash
cd /path/to/fpl-bot
git init
git add .
git commit -m "Initial commit - FPL Bot Lite"
git branch -M main
git remote add origin git@github.com:YOUR-USER/fpl-bot.git
git push -u origin main
