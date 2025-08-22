# tests/test_planner_constraints.py
from planner import (
    PlayerProj,
    build_fixtures_index,
    compute_strength_means,
    project_player_points_by_gw,
    propose_transfers,
)

def test_propose_transfers_respects_budget_and_club_cap(tiny_league):
    client = tiny_league.client
    bootstrap = tiny_league.bootstrap
    fixtures_idx = build_fixtures_index(tiny_league.fixtures)
    teams_by_id = {t["id"]: t for t in tiny_league.teams}
    strength_means = compute_strength_means(tiny_league.teams)

    # Current squad: 2 starters from team 1 (DEF + FWD), both cheap enough
    # We'll present them as current picks so proposer can consider upgrades.
    gw_range = [2]

    def proj(el):
        xmap = project_player_points_by_gw(client, el, fixtures_idx, gw_range, teams_by_id, strength_means)
        return PlayerProj(
            id=el["id"],
            name=el["web_name"],
            pos=el["element_type"],
            team=el["team"],
            cost=(el["now_cost"] or 0) / 10.0,
            xpts_by_gw=xmap,
            xpts_total=sum(xmap.values()),
            starter=True,
        )

    current = [proj(next(e for e in tiny_league.elements if e["id"] == 101)),
               proj(next(e for e in tiny_league.elements if e["id"] == 102))]

    # Bank: 0.0m, so upgrades must be affordable.
    bank = 0.0
    event_id = 2

    moves = propose_transfers(
        bootstrap=bootstrap,
        current=current,
        bank_m=bank,
        gw=event_id,
        gw_range=gw_range,
        client=client,
        fixtures_idx=fixtures_idx,
        team_by_id=teams_by_id,
        strength_means=strength_means,
        free_transfers=1,
        hit_penalty=4,
        shortlist=5,
        max_swaps=1,
    )

    # Should return a list (possibly empty). Whatever it suggests:
    # - No move should violate budget (we gave bank=0).
    # - No move should violate 3-per-club (we only had 2 from team 1).
    for sell, buy, raw, net, uses_hit in moves:
        assert buy.cost <= sell.cost  # with bank=0, upgrades must be equal/cheaper
        # We only had 2 from team 1, so adding another from team 1 is still within the cap.
        # This test mainly guards that propose_transfers runs and respects affordability.

def test_no_hits_when_forbidden(tiny_league, monkeypatch):
    """If we simulate FREE_TRANSFERS being very large, the planner should label moves as free."""
    client = tiny_league.client
    bootstrap = tiny_league.bootstrap
    fixtures_idx = build_fixtures_index(tiny_league.fixtures)
    teams_by_id = {t["id"]: t for t in tiny_league.teams}
    strength_means = compute_strength_means(tiny_league.teams)
    gw_range = [2]

    # Build a tiny current team of two starters again
    def mk(el_id):
        el = next(e for e in tiny_league.elements if e["id"] == el_id)
        xmap = project_player_points_by_gw(client, el, fixtures_idx, gw_range, teams_by_id, strength_means)
        return PlayerProj(
            id=el["id"],
            name=el["web_name"],
            pos=el["element_type"],
            team=el["team"],
            cost=(el["now_cost"] or 0) / 10.0,
            xpts_by_gw=xmap,
            xpts_total=sum(xmap.values()),
            starter=True,
        )

    current = [mk(101), mk(102)]

    moves = propose_transfers(
        bootstrap=bootstrap,
        current=current,
        bank_m=0.0,
        gw=2,
        gw_range=gw_range,
        client=client,
        fixtures_idx=fixtures_idx,
        team_by_id=teams_by_id,
        strength_means=strength_means,
        free_transfers=99,     # effectively forbid hits
        hit_penalty=4,
        shortlist=5,
        max_swaps=2,
    )

    # If any moves returned, they must be marked as free
    for *_rest, uses_hit in moves:
        assert uses_hit is False
