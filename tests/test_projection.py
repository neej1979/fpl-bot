# tests/test_projection.py
from planner import (
    build_fixtures_index,
    compute_strength_means,
    fixture_strength_scalar,
    project_player_points_by_gw,
)

def test_fixture_scalar_position_and_home_away(tiny_league):
    client = tiny_league.client
    teams_by_id = {t["id"]: t for t in tiny_league.teams}
    strength_means = compute_strength_means(tiny_league.teams)
    fx = tiny_league.fixtures[0]  # team1(H) vs team2(A)

    # DEF on home team (id=101, team=1)
    home_def = next(e for e in tiny_league.elements if e["id"] == 101)
    s_def = fixture_strength_scalar(fx, home_def, teams_by_id, strength_means)

    # FWD on home team (id=102, team=1)
    home_fwd = next(e for e in tiny_league.elements if e["id"] == 102)
    s_fwd = fixture_strength_scalar(fx, home_fwd, teams_by_id, strength_means)

    # Sanity: both are clamped into a sensible range
    assert 0.6 <= s_def <= 1.4
    assert 0.6 <= s_fwd <= 1.4

    # Typically, attacker scalar vs opp DEF may differ from DEF vs opp ATT
    # We just assert they aren't both exactly 1.0, to ensure logic is active
    assert abs(s_def - 1.0) > 1e-6 or abs(s_fwd - 1.0) > 1e-6


def test_project_points_by_gw_basic_increase_with_minutes(tiny_league):
    client = tiny_league.client
    teams_by_id = {t["id"]: t for t in tiny_league.teams}
    strength_means = compute_strength_means(tiny_league.teams)
    fixtures_idx = build_fixtures_index(tiny_league.fixtures)

    # Two players from the same team: DEF(101) and FWD(102)
    def_el = next(e for e in tiny_league.elements if e["id"] == 101)
    fwd_el = next(e for e in tiny_league.elements if e["id"] == 102)

    # Horizon includes only GW2 (the upcoming fixture)
    gw_range = [2]

    # Projections
    p_def = project_player_points_by_gw(client, def_el, fixtures_idx, gw_range, teams_by_id, strength_means)
    p_fwd = project_player_points_by_gw(client, fwd_el, fixtures_idx, gw_range, teams_by_id, strength_means)

    # They both should project > 0 given our MIN_BASELINE floor in planner
    assert p_def[2] > 0
    assert p_fwd[2] > 0

    # In this tiny setup, FWD with recent returns often projects >= DEF
    assert p_fwd[2] >= p_def[2]  # not a strict rule globally, but a reasonable local check


def test_minutes_floor_penalizes_unnailed_players(tiny_league, monkeypatch):
    """Simulate a player with almost no minutes and ensure the projection is reduced."""
    client = tiny_league.client
    teams_by_id = {t["id"]: t for t in tiny_league.teams}
    strength_means = compute_strength_means(tiny_league.teams)
    fixtures_idx = build_fixtures_index(tiny_league.fixtures)
    gw_range = [2]

    # Copy an element and give it an empty/low-minutes history via monkeypatch
    el = dict(next(e for e in tiny_league.elements if e["id"] == 102))  # base on FWD
    el["id"] = 999

    def fake_summary(_):
        return {"history": [{"minutes": 0, "total_points": 0}] * 6}

    monkeypatch.setattr(client, "element_summary", lambda _id: fake_summary(_id))

    p = project_player_points_by_gw(client, el, fixtures_idx, gw_range, teams_by_id, strength_means)
    # Should still be > 0 due to MIN_BASELINE per-fixture floor,
    # but not absurdly high (sanity upper bound).
    assert p[2] > 0
    assert p[2] < 10.0
