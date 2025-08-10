#!/usr/bin/env python3
import argparse, statistics
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Iterable
from fpl_client import FPLClient, SnapshotClient

def resolve_picks_with_fallback(client, bootstrap, team_id:int, event_id:int):
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
    xpts_by_gw: Dict[int, float]
    xpts_total: float
    starter: bool

def get_current_event(bootstrap: Dict[str, Any]) -> int:
    current = [e for e in bootstrap["events"] if e.get("is_current")]
    if current: return current[0]["id"]
    upcoming = [e for e in bootstrap["events"] if not e.get("is_finished") and not e.get("is_previous")]
    if upcoming: return upcoming[0]["id"]
    return max(e["id"] for e in bootstrap["events"])

def recent_points_ppA(history: List[Dict[str,Any]], n:int=8, decay:float=0.88) -> float:
    recent = [h for h in history[-n:] if h.get("minutes",0)>0]
    if not recent: return 0.0
    w=1.0; num=0.0; den=0.0
    for h in reversed(recent):
        num += h.get("total_points",0)*w
        den += w
        w *= decay
    return num/(den or 1.0)

def minutes_scalar(history: List[Dict[str,Any]], player: Dict[str,Any]) -> float:
    mins=[h.get("minutes",0) for h in history[-6:] if h.get("minutes",0)>0]
    m_rate = min(1.0, (sum(mins)/len(mins)/90.0)) if mins else 0.0
    if player.get("chance_of_playing_next_round") is not None:
        c = max(0.0, min(1.0, player["chance_of_playing_next_round"]/100.0))
    else:
        status=player.get("status","a")
        c = 1.0 if status=="a" else (0.75 if status=="d" else (0.25 if status=="f" else 0.0))
    return 0.6*c+0.4*m_rate

def fixture_scalars(fixt: Dict[str,Any], player_team:int):
    if fixt["team_h"]==player_team:
        diff=fixt.get("team_h_difficulty",3); home=True
    else:
        diff=fixt.get("team_a_difficulty",3); home=False
    diff_s = 1.12 if diff<=2 else (1.0 if diff==3 else 0.90)
    ha_s = 1.05 if home else 0.95
    return diff_s, ha_s

def build_fixtures_index(fixtures:List[Dict[str,Any]]):
    idx={}
    for f in fixtures:
        ev=f.get("event")
        if ev is None: continue
        for t in (f["team_h"], f["team_a"]):
            idx.setdefault(t,{}).setdefault(ev,[]).append(f)
    return idx

def project_player_points_by_gw(client, player, fixtures_idx, gw_range:Iterable[int]):
    summ=client.element_summary(player["id"])
    hist=summ.get("history",[])
    base=recent_points_ppA(hist) or float(player.get("form") or 0.0)
    ms=minutes_scalar(hist, player)
    team=player["team"]
    out={}
    for ev in gw_range:
        fxs=fixtures_idx.get(team,{}).get(ev,[])
        if not fxs:
            out[ev]=base*0.1*ms*0.3
        else:
            total=0.0
            for f in fxs:
                diff_s, ha_s = fixture_scalars(f, team)
                total += base*diff_s*ha_s*ms
            out[ev]=total
    return out

def suggest_captain_and_bench(projs:List[PlayerProj], gw:int):
    starters=[p for p in projs if p.starter]
    bench=[p for p in projs if not p.starter]
    bench.sort(key=lambda p: (p.xpts_by_gw.get(gw,0.0), p.pos==1))
    captain=max(starters, key=lambda p: p.xpts_by_gw.get(gw,0.0))
    return captain, bench

def propose_transfers(bootstrap, current, bank_m, gw, horizon, client, fixtures_idx, free_transfers=1, hit_penalty=4, shortlist=80, max_swaps=2):
    by_id={p.id:p for p in current}
    elements=bootstrap["elements"]
    candidates=sorted(elements, key=lambda e: float(e.get("form") or 0.0), reverse=True)[:shortlist]
    cand_x={}
    for c in candidates:
        cand_x[c["id"]]=sum(project_player_points_by_gw(client,c,fixtures_idx,horizon).values())
    club_counts={}
    for p in current:
        club_counts[p.team]=club_counts.get(p.team,0)+1
    def can_add(tid): return club_counts.get(tid,0)<3
    by_pos={}
    for p in current:
        by_pos.setdefault(p.pos,[]).append(p)
    sells={}
    for pos,arr in by_pos.items():
        arr.sort(key=lambda p:p.xpts_total)
        if arr: sells[pos]=arr[0]
    props=[]; swaps=0; bank=bank_m
    for pos,to_sell in sorted(sells.items(), key=lambda kv: kv[1].xpts_total):
        budget=bank+to_sell.cost
        best=None; best_gain=0.0
        for c in candidates:
            if c["element_type"]!=pos: continue
            if c["id"] in by_id: continue
            price=c["now_cost"]/10.0
            if price>budget+1e-6: continue
            if not can_add(c["team"]): continue
            gain=cand_x[c["id"]] - to_sell.xpts_total
            if gain>best_gain+0.01:
                best_gain=gain; best=c
        if best and best_gain>0.2:
            swaps+=1
            hit=0 if swaps<=free_transfers else hit_penalty
            props.append((to_sell,
                          PlayerProj(best["id"],best["web_name"],best["element_type"],best["team"],best["now_cost"]/10.0,{},cand_x[best["id"]],True),
                          best_gain, best_gain-hit))
            club_counts[to_sell.team]-=1
            club_counts[best["team"]] = club_counts.get(best["team"],0)+1
            bank=bank+to_sell.cost - best["now_cost"]/10.0
            if len(props)>=max_swaps: break
    props=[p for p in sorted(props, key=lambda x:x[3], reverse=True) if p[3]>0.0]
    return props

def detect_double_gameweeks(fixtures, gw):
    counts={}
    for f in fixtures:
        if f.get("event")!=gw: continue
        for t in (f["team_h"], f["team_a"]):
            counts[t]=counts.get(t,0)+1
    return {t:c for t,c in counts.items() if c>1}

def chip_suggestions(projs, gw, fixtures):
    out=[]
    bench=[p for p in projs if not p.starter]
    bench_x=sum(p.xpts_by_gw.get(gw,0.0) for p in bench)
    if bench_x>=12.0: out.append(f"Bench Boost looks viable (bench xPts ≈ {bench_x:.1f}).")
    dgw=detect_double_gameweeks(fixtures, gw)
    starters=[p for p in projs if p.starter]
    if starters:
        cap=max(starters, key=lambda p:p.xpts_by_gw.get(gw,0.0))
        if dgw.get(cap.team,1)>1: out.append(f"Triple Captain candidate: {cap.name} (team has a DGW).")
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--team-id", type=int, required=True)
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--free-transfers", type=int, default=1)
    ap.add_argument("--hit-penalty", type=int, default=4)
    ap.add_argument("--shortlist", type=int, default=80)
    ap.add_argument("--snapshot-dir", type=str, default=None)
    args=ap.parse_args()

    client = SnapshotClient(args.snapshot_dir) if args.snapshot_dir else FPLClient()
    bootstrap=client.bootstrap()
    fixtures=client.fixtures()
    fixtures_idx=build_fixtures_index(fixtures)
    event_id=get_current_event(bootstrap)
    entry=client.entry(args.team_id)
    event_id, picks = resolve_picks_with_fallback(client, bootstrap, args.team_id, event_id)

    elements={e["id"]:e for e in bootstrap["elements"]}
    team_by_id={t["id"]:t for t in bootstrap["teams"]}
    events_sorted=[e["id"] for e in sorted(bootstrap["events"], key=lambda x:x["id"])]
    start_idx=events_sorted.index(event_id)
    gw_range=events_sorted[start_idx:start_idx+args.horizon]

    projs=[]
    for p in picks["picks"]:
        el=elements[p["element"]]
        is_starter=p.get("position",0)<=11
        xgw=project_player_points_by_gw(client, el, fixtures_idx, gw_range)
        xtot=sum(xgw.values())
        projs.append(PlayerProj(el["id"], el["web_name"], el["element_type"], el["team"], el["now_cost"]/10.0, xgw, xtot, is_starter))

    captain, bench = suggest_captain_and_bench(projs, event_id)
    bank=entry.get("bank",0)/10.0
    transfers=propose_transfers(bootstrap, projs, bank, event_id, gw_range, client, fixtures_idx,
                                free_transfers=args.free_transfers, hit_penalty=args.hit_penalty,
                                shortlist=args.shortlist, max_swaps=2)

    def fmt(p):
        gw_now=p.xpts_by_gw.get(event_id,0.0)
        return f"{p.name:<20} {POS_INV[p.pos]:<3} £{p.cost:>4.1f}  GW{event_id}:{gw_now:>5.2f}  {args.horizon}GW:{p.xpts_total:>6.2f}  {team_by_id[p.team]['short_name']}"

    print(f"\nFPL Planner – Team {args.team_id}")
    print(f"Current GW: {event_id} | Horizon: {args.horizon} GWs | Bank: £{bank:.1f}m | FTs: {args.free_transfers} | Hit: -{args.hit_penalty} per extra\n")

    starters = sorted([p for p in projs if p.starter], key=lambda x:x.xpts_by_gw.get(event_id,0.0), reverse=True)
    print("Starters (sorted by GW xPts):")
    for p in starters: print("  ", fmt(p))

    print("\nBench order (low GW xPts first):")
    for p in bench: print("  ", fmt(p))

    print("\nCaptain suggestion:")
    print("  ", fmt(captain))

    tips=chip_suggestions(projs, event_id, fixtures)
    if tips:
        print("\nChip planning signals:")
        for t in tips: print("  -", t)

    if transfers:
        print("\nTransfer suggestions (xPts over horizon; raw vs net after hits):")
        for sell,buy,raw,net in transfers:
            print(f"  SELL  {sell.name:<20} {POS_INV[sell.pos]:<3} £{sell.cost:>4.1f}  {args.horizon}GW:{sell.xpts_total:>6.2f}")
            print(f"  BUY   {buy.name:<20}  {POS_INV[buy.pos]:<3} £{buy.cost:>4.1f}  {args.horizon}GW:{buy.xpts_total:>6.2f}")
            print(f"  ==> Gain: +{raw:.2f} xPts | Net after hits: {net:+.2f}\n")
    else:
        print("\nNo positive net-EV transfer found given FTs/hit. Consider rolling.")
    print("\nDone.")

if __name__=='__main__':
    main()
