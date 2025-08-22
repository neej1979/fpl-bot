#!/usr/bin/env python3
import statistics
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Iterable
import os, yaml, requests
from fpl_client import FPLClient, SnapshotClient

# ---------- config ----------
def load_config() -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "config.yaml"),
        os.path.join(os.path.dirname(here), "config.yaml"),
    ]
    for p in candidates:
        if os.path.exists(p):
            with open(p, "r") as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("config.yaml not found next to planner.py or in repo root.")

config = load_config()

# core settings
TEAM_ID        = config["team_id"]
HORIZON        = config["horizon"]
FREE_TRANSFERS = config.get("free_transfers", 1)
HIT_PENALTY    = config.get("hit_penalty", 4)
SHORTLIST      = config.get("shortlist", 80)
SNAPSHOT_DIR   = config.get("snapshot_dir", None)
REGRESSION_FACTOR = 0.5   # How much to regress to mean (0 = no regression, 1 = full regression)
MIN_BASELINE = 2.0        # A floor so no projection drops below this average
# Baselines per position (per-game, rough FPL reality)
# 1=GK, 2=DEF, 3=MID, 4=FWD
POS_BASELINES = {
    1: 3.5,
    2: 3.0,
    3: 4.8,
    4: 5.2,
}
MIN_RAW_GAIN = 2.0     # ignore tiny upgrades even before hits
MIN_NET_GAIN = 0.5     # require at least +0.5 AFTER hits to recommend
REQUIRE_NO_HIT = False # set True if you only want moves that use a free FT
GK_SWAP_MIN_GAIN = 8.0   # require ≥8 xPts over horizon if swapping a bench GK (or skip)



# auth + headers (for pre-deadline private endpoints)
AUTH_HEADER    = config.get("auth_header", "")   # "Bearer eyJ..."
USER_AGENT     = config.get("user_agent", None)
REFERER        = config.get("referer", None)

# ---------- shared helpers ----------
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

def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def compute_strength_means(teams: list[dict]) -> dict:
    # League means to normalize opponent strengths into ~1.0
    n = len(teams) or 1
    get = lambda k: sum(float(t.get(k, 0) or 0) for t in teams) / n
    return {
        "att_home": get("strength_attack_home"),
        "att_away": get("strength_attack_away"),
        "def_home": get("strength_defence_home"),
        "def_away": get("strength_defence_away"),
    }

def fixture_strength_scalar(fixt: dict, player: dict, teams_by_id: dict, strength_means: dict) -> float:
    """
    Returns a single multiplicative scalar for the fixture based on:
      - opponent attack/defence strength (home/away)
      - player's position (attackers face opp DEF; GK/DEF face opp ATT)
      - small home/away bump for the player's team
    """
    player_team = player["team"]
    pos = player.get("element_type", 4)  # 1 GK, 2 DEF, 3 MID, 4 FWD
    player_is_home = (fixt["team_h"] == player_team)

    opp_id = fixt["team_a"] if player_is_home else fixt["team_h"]
    opp = teams_by_id.get(opp_id, {})

    # opponent strength fields
    if player_is_home:
        # opponent is away
        opp_att = float(opp.get("strength_attack_away", 0) or 0)
        opp_def = float(opp.get("strength_defence_away", 0) or 0)
        mean_att = float(strength_means.get("att_away", 1.0) or 1.0)
        mean_def = float(strength_means.get("def_away", 1.0) or 1.0)
    else:
        # opponent is home
        opp_att = float(opp.get("strength_attack_home", 0) or 0)
        opp_def = float(opp.get("strength_defence_home", 0) or 0)
        mean_att = float(strength_means.get("att_home", 1.0) or 1.0)
        mean_def = float(strength_means.get("def_home", 1.0) or 1.0)

    # normalize: stronger opp → scalar < 1; weaker opp → scalar > 1
    if pos in (3, 4):  # attacker faces opponent DEF
        base = (mean_def / opp_def) if opp_def > 0 else 1.0
    else:              # GK/DEF face opponent ATT
        base = (mean_att / opp_att) if opp_att > 0 else 1.0

    base = _clamp(base, 0.6, 1.4)  # keep within sane bounds
    ha = 1.05 if player_is_home else 0.95  # small home/away edge for the player's team

    return base * ha


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
    events = bootstrap["events"]

    # Prefer the next gameweek when the site marks one
    nxt = [e for e in events if e.get("is_next")]
    if nxt:
        return nxt[0]["id"]

    # Otherwise use the current GW (bump if already finished)
    cur = [e for e in events if e.get("is_current")]
    if cur:
        e = cur[0]
        if e.get("is_finished", False):
            return e["id"] + 1
        return e["id"]

    # Fallbacks
    unfinished = [ev for ev in events if not ev.get("is_finished", False)]
    if unfinished:
        return min(unfinished, key=lambda x: x["id"])["id"]
    return max(ev["id"] for ev in events)




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

def project_player_points_by_gw(client, player, fixtures_idx, gw_range,
                                teams_by_id, strength_means):
    """
    Per-GW projection with:
      - recent points per appearance
      - regression to position baseline (using REGRESSION_FACTOR)
      - minutes floor (nerfs if not nailed)
      - opponent strength (home/away, attack/defence)
      - per-fixture floor via MIN_BASELINE to avoid silly tiny numbers
    """
    summ = client.element_summary(player["id"])
    hist = summ.get("history", [])

    # 1) recent per-appearance points (your decayed rpPA)
    recent_pts = recent_points_ppA(hist)

    # 2) regression target = baseline by position
    pos = player.get("element_type", 4)
    baseline = POS_BASELINES.get(pos, 3.5)

    # 3) regression mix:
    #    REGRESSION_FACTOR = 0 → use recent only
    #    REGRESSION_FACTOR = 1 → use baseline only
    base = (1.0 - REGRESSION_FACTOR) * recent_pts + REGRESSION_FACTOR * baseline

    # 4) minutes expectation (with simple floor if not nailed)
    ms = minutes_scalar(hist, player)
    recent_mins = [h.get("minutes", 0) for h in hist[-3:]]
    if sum(1 for m in recent_mins if m >= 30) < 2:
        ms *= 0.7   # gentler nerf than before so we’re not overly negative

    team = player["team"]
    out = {}

    for ev in gw_range:
        fxs = fixtures_idx.get(team, {}).get(ev, [])
        if not fxs:
            out[ev] = 0.0
            continue

        total = 0.0
        for f in fxs:
            s = fixture_strength_scalar(f, player, teams_by_id, strength_means)

            # raw contribution for this fixture
            contrib = base * ms * s

            # 5) gentle per-fixture floor so we aren’t absurdly pessimistic
            #    MIN_BASELINE is interpreted as “floor per fixture”
            contrib = max(contrib, MIN_BASELINE)

            total += contrib

        out[ev] = total

    return out




def suggest_captain_and_bench(projs:List[PlayerProj], gw:int):
    starters=[p for p in projs if p.starter]
    bench=[p for p in projs if not p.starter]
    bench.sort(key=lambda p: (p.xpts_by_gw.get(gw,0.0), p.pos==1))
    captain=max(starters, key=lambda p: p.xpts_by_gw.get(gw,0.0))
    return captain, bench

def propose_transfers(
    bootstrap,
    current: List[PlayerProj],
    bank_m: float,
    gw: int,
    gw_range: Iterable[int],
    client,
    fixtures_idx,
    team_by_id: Dict[int, dict],
    strength_means: Dict[str, float],
    free_transfers: int = 1,
    hit_penalty: int = 4,
    shortlist: int = 80,
    max_swaps: int = 2,
):
    by_id = {p.id: p for p in current}
    elements = bootstrap["elements"]

    # Rank candidates by projected xPts over the horizon (safer than "form")
    scored = []
    for e in elements:
        xmap = project_player_points_by_gw(client, e, fixtures_idx, gw_range, team_by_id, strength_means)
        xtot = sum(xmap.values())
        scored.append((xtot, e))
    candidates = [e for (xtot, e) in sorted(scored, key=lambda t: t[0], reverse=True)[:shortlist]]

    # Precompute candidate totals
    cand_x = {}
    for c in candidates:
        cand_x[c["id"]] = sum(
            project_player_points_by_gw(client, c, fixtures_idx, gw_range, team_by_id, strength_means).values()
        )

    # Club counts (max 3 rule)
    club_counts = {}
    for p in current:
        club_counts[p.team] = club_counts.get(p.team, 0) + 1

    def can_add(tid): 
        return club_counts.get(tid, 0) < 3

    # Group current by position, choose weakest as sell
    by_pos = {}
    for p in current:
        by_pos.setdefault(p.pos, []).append(p)

    sells = {}
    for pos, arr in by_pos.items():
        arr.sort(key=lambda p: p.xpts_total)
        if arr:
            sells[pos] = arr[0]

    props = []
    swaps = 0
    bank = bank_m

    # For each position's weakest, find the best affordable upgrade
    for pos, to_sell in sorted(sells.items(), key=lambda kv: kv[1].xpts_total):
        budget = bank + to_sell.cost
        best = None
        best_gain = 0.0

        for c in candidates:
            if c["element_type"] != pos:
                continue
            if c["id"] in by_id:
                continue
            price = (c.get("now_cost") or 0) / 10.0
            if price > budget + 1e-6:
                continue
            if not can_add(c["team"]):
                continue

            gain = cand_x[c["id"]] - to_sell.xpts_total
            if gain > best_gain + 0.01:
                best_gain = gain
                best = c

        if best and best_gain > 0.2:
            # avoid paying for bench GK swaps unless they're huge
            if pos == 1 and not to_sell.starter:
                # If this is a bench GK and the gain isn't huge, skip.
                if best_gain < GK_SWAP_MIN_GAIN or swaps >= free_transfers:
                    continue

            swaps += 1
            hit = 0 if swaps <= free_transfers else hit_penalty

            # NEW: project points per GW for the buy, not just total
            buy_xmap = project_player_points_by_gw(client, best, fixtures_idx, gw_range, team_by_id, strength_means)
            buy_xtot = sum(buy_xmap.values())

            props.append(
                (
                    to_sell,
                    PlayerProj(
                        best["id"],
                        best["web_name"],
                        best["element_type"],
                        best["team"],
                        (best.get("now_cost") or 0) / 10.0,
                        buy_xmap,      # <--- this was {} before
                        buy_xtot,      # <--- use real total
                        True,
                    ),
                    best_gain,
                    best_gain - hit,
                )
            )

            club_counts[to_sell.team] -= 1
            club_counts[best["team"]] = club_counts.get(best["team"], 0) + 1
            bank = bank + to_sell.cost - ((best.get("now_cost") or 0) / 10.0)
            if len(props) >= max_swaps:
                break


    # --- Final sanity gates (outside the loop) ---
    props = [p for p in sorted(props, key=lambda x: x[3], reverse=True)]

    MIN_BUY_XPTS = 6.0        # Don't buy someone who projects <6.0 total
    REQUIRE_STARTER_UPGRADE = True  # Only if it improves your starting XI

    # Worst current STARTER by position
    worst_starter_by_pos = {}
    for p in current:
        if p.starter:
            w = worst_starter_by_pos.get(p.pos)
            if (w is None) or (p.xpts_total < w.xpts_total):
                worst_starter_by_pos[p.pos] = p

    filtered = []
    for sell, buy, raw, net in props:
        if raw < MIN_RAW_GAIN:
            continue
        if buy.xpts_total < MIN_BUY_XPTS:
            continue
        if REQUIRE_STARTER_UPGRADE:
            worst = worst_starter_by_pos.get(buy.pos)
            if worst and (buy.xpts_total <= worst.xpts_total):
                continue
        filtered.append((sell, buy, raw, net))
    
        # Recompute hits AFTER filtering, so the first kept move uses free FT(s)
    filtered.sort(key=lambda x: x[2], reverse=True)  # raw gain desc

    final = []
    for i, (sell, buy, raw, _old_net) in enumerate(filtered, start=1):
        hit = 0 if i <= free_transfers else hit_penalty
        net = raw - hit
        uses_hit = (hit > 0)
        # apply final gates
        if raw < MIN_RAW_GAIN: 
            continue
        if REQUIRE_NO_HIT and uses_hit:
            continue
        if net < MIN_NET_GAIN:
            continue
        final.append((sell, buy, raw, net, uses_hit))

    return final


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

# ---------- main ----------
def main():
    # Build client: snapshot or live with auth headers
    if SNAPSHOT_DIR:
        client = SnapshotClient(SNAPSHOT_DIR)
    else:
        client = FPLClient(
            auth_header=AUTH_HEADER,
            user_agent=USER_AGENT,
            referer=REFERER,
        )

    bootstrap=client.bootstrap()
    fixtures=client.fixtures()
    fixtures_idx=build_fixtures_index(fixtures)
    event_id=get_current_event(bootstrap)
    entry=client.entry(TEAM_ID)

    # Build GW range from config horizon
    events_sorted=[e["id"] for e in sorted(bootstrap["events"], key=lambda x:x["id"])]
    start_idx=events_sorted.index(event_id)
    gw_range=events_sorted[start_idx:start_idx+HORIZON]

    # Fetch picks with pre-deadline fallback to /my-team/
    try:
        event_id, picks = resolve_picks_with_fallback(client, bootstrap, TEAM_ID, event_id)
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if AUTH_HEADER and status in (401, 403, 404):
            my = client.my_team(TEAM_ID)
            picks = {"picks": my["picks"], "active_chip": my.get("active_chip")}
        else:
            raise

    elements={e["id"]:e for e in bootstrap["elements"]}
    team_by_id={t["id"]:t for t in bootstrap["teams"]}
    strength_means = compute_strength_means(bootstrap["teams"])


    projs=[]
    for p in picks["picks"]:
        el=elements[p["element"]]
        is_starter=p.get("position",0)<=11
        xgw = project_player_points_by_gw(client, el, fixtures_idx, gw_range, team_by_id, strength_means)
        xtot=sum(xgw.values())
        projs.append(PlayerProj(el["id"], el["web_name"], el["element_type"], el["team"], el["now_cost"]/10.0, xgw, xtot, is_starter))

    captain, bench = suggest_captain_and_bench(projs, event_id)
    bank=entry.get("bank",0)/10.0
    transfers = propose_transfers(
        bootstrap,
        projs,
        bank,
        event_id,
        gw_range,
        client,
        fixtures_idx,
        team_by_id,
        strength_means,
        free_transfers=FREE_TRANSFERS,
        hit_penalty=HIT_PENALTY,
        shortlist=SHORTLIST,
        max_swaps=2,
)


    def fmt(p):
        gw_now = p.xpts_by_gw.get(event_id, 0.0)
        avg = p.xpts_total / len(gw_range) if gw_range else 0.0
        return (
            f"{p.name:<20} {POS_INV[p.pos]:<3} £{p.cost:>4.1f}  "
            f"GW{event_id}:{gw_now:>5.2f}  {HORIZON}GW:{p.xpts_total:>6.2f} (avg {avg:.2f})  "
            f"{team_by_id[p.team]['short_name']}"
        )

    print(f"\nFPL Planner – Team {TEAM_ID}")
    print(f"Current GW: {event_id} | Horizon: {HORIZON} GWs | Bank: £{bank:.1f}m | FTs: {FREE_TRANSFERS} | Hit: -{HIT_PENALTY} per extra\n")

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
        for sell, buy, raw, net, uses_hit in transfers:
            hit_note = " (free)" if not uses_hit else f" (uses -{HIT_PENALTY} hit)"

            # Short-term impact this GW
            delta_now = buy.xpts_by_gw.get(event_id, 0.0) - sell.xpts_by_gw.get(event_id, 0.0)
            if delta_now < -0.25 and net > 0:
                st_note = " [short-term down, long-term up]"
            elif delta_now > 0.25 and net < 0:
                st_note = " [short-term up, long-term down]"
            else:
                st_note = ""

            print(f"  SELL  {sell.name:<20} {POS_INV[sell.pos]:<3} £{sell.cost:>4.1f}  {HORIZON}GW:{sell.xpts_total:>6.2f}")
            print(f"  BUY   {buy.name:<20}  {POS_INV[buy.pos]:<3} £{buy.cost:>4.1f}  {HORIZON}GW:{buy.xpts_total:>6.2f}")
            print(f"  ==> Gain: +{raw:.2f} xPts | Net after hits: {net:+.2f}{hit_note} | GW{event_id} Δ: {delta_now:+.2f}{st_note}\n")
    else:
        print("\nNo positive net-EV transfer found given FTs/hit. Consider rolling.")
        print("\nDone.")

if __name__=='__main__':
    main()
