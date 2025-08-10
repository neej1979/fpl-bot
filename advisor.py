#!/usr/bin/env python3
import argparse, statistics
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
from fpl_client import FPLClient, SnapshotClient

def resolve_picks_with_fallback(client, bootstrap, team_id:int, event_id:int):
    """Try current GW picks; if fails (e.g., pre-season), fallback to last finished GW."""
    try:
        return event_id, client.entry_picks(team_id, event_id)
    except Exception:
        prev = [ev for ev in bootstrap["events"] if ev.get("is_previous")]
        if prev:
            prev_id = max(prev, key=lambda x: x["id"])["id"]
            return prev_id, client.entry_picks(team_id, prev_id)
        raise

POS_INV = {1:"GK",2:"DEF",3:"MID",4:"FWD"}

@dataclass
class PlayerProj:
    id: int
    name: str
    pos: int
    team: int
    cost: float
    exp_points: float
    starter: bool

def get_current_event(bootstrap: Dict[str, Any]) -> int:
    for e in bootstrap["events"]:
        if e.get("is_current") or (not e.get("is_finished") and not e.get("is_previous")):
            return e["id"]
    return max(e["id"] for e in bootstrap["events"] if not e.get("is_finished", False))

def recent_points_ppA(history: List[Dict[str,Any]], n:int=6) -> float:
    recent = [h for h in history[-n:] if h.get("minutes",0)>0]
    if not recent: return 0.0
    pts = [h.get("total_points",0) for h in recent]
    return statistics.mean(pts)

def fixture_difficulty_scalar(fixt: Dict[str,Any], player_team:int) -> float:
    diff = fixt.get("team_h_difficulty",3) if fixt["team_h"]==player_team else fixt.get("team_a_difficulty",3)
    return 1.1 if diff<=2 else (1.0 if diff==3 else 0.9)

def chance_to_play_scalar(player: Dict[str,Any]) -> float:
    if player.get("chance_of_playing_next_round") is not None:
        return max(0.0, min(1.0, player["chance_of_playing_next_round"]/100.0))
    status = player.get("status","a")
    return 1.0 if status=="a" else (0.75 if status=="d" else (0.25 if status=="f" else 0.0))

def build_team_fixture_index(fixtures:List[Dict[str,Any]])->Dict[int,List[Dict[str,Any]]]:
    by_team={}
    for f in fixtures:
        for t in (f["team_h"], f["team_a"]):
            by_team.setdefault(t, []).append(f)
    for t in by_team:
        by_team[t].sort(key=lambda x: (x.get("kickoff_time") or ""))
    return by_team

def project_player_points(client, player:Dict[str,Any], horizon:int, team_fixtures_by_team:Dict[int,List[Dict[str,Any]]]) -> float:
    summ = client.element_summary(player["id"])
    hist = summ.get("history", [])
    base_ppA = recent_points_ppA(hist, n=6) or float(player.get("form") or 0.0)
    minutes_s = chance_to_play_scalar(player)
    upcoming = [f for f in team_fixtures_by_team.get(player["team"],[]) if f.get("event") is not None][:horizon] or []
    exp=0.0
    for f in upcoming:
        exp += base_ppA * fixture_difficulty_scalar(f, player["team"]) * minutes_s
    return exp or (base_ppA * minutes_s)

def suggest_captain_and_bench(projs:List[PlayerProj]) -> Tuple[PlayerProj, List[PlayerProj]]:
    starters=[p for p in projs if p.starter]
    bench=[p for p in projs if not p.starter]
    bench.sort(key=lambda p: (p.exp_points, p.pos==1))
    captain=max(starters, key=lambda p: p.exp_points)
    return captain, bench

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--team-id", type=int, required=True)
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--snapshot-dir", type=str, default=None, help="Offline snapshot directory")
    args=ap.parse_args()

    client = SnapshotClient(args.snapshot_dir) if args.snapshot_dir else FPLClient()
    bootstrap = client.bootstrap()
    fixtures = client.fixtures()
    team_fixt_idx = build_team_fixture_index(fixtures)
    event_id = get_current_event(bootstrap)
    entry = client.entry(args.team_id)
    event_id, picks = resolve_picks_with_fallback(client, bootstrap, args.team_id, event_id)

    elements={e["id"]:e for e in bootstrap["elements"]}
    team_by_id={t["id"]:t for t in bootstrap["teams"]}

    projs: List[PlayerProj]=[]
    for p in picks["picks"]:
        el=elements[p["element"]]
        is_starter = p.get("position",0)<=11
        exp = project_player_points(client, el, args.horizon, team_fixt_idx)
        projs.append(PlayerProj(id=el["id"], name=el["web_name"], pos=el["element_type"], team=el["team"], cost=el["now_cost"]/10.0, exp_points=exp, starter=is_starter))

    captain, bench = suggest_captain_and_bench(projs)
    bank = entry.get("bank",0)/10.0

    def fmt(p:PlayerProj)->str:
        return f"{p.name:<20} {POS_INV[p.pos]:<3} £{p.cost:>4.1f}  xPts:{p.exp_points:>5.2f}  Club:{team_by_id[p.team]['short_name']}"

    print(f"\nFPL Bot Lite – Advisor for Team {args.team_id}")
    print(f"Using GW {event_id} | Horizon {args.horizon} | Bank: £{bank:.1f}m\n")

    starters = sorted([p for p in projs if p.starter], key=lambda x: x.exp_points, reverse=True)
    print("Starters (sorted by projected points):")
    for p in starters: print("  ", fmt(p))

    print("\nBench order (low xPts first):")
    for p in bench: print("  ", fmt(p))

    print("\nCaptain suggestion:")
    print("  ", fmt(captain))

    print("\nDone.")
if __name__=='__main__':
    main()
