# tests/conftest.py
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest
from types import SimpleNamespace

class FakeClient:
    """
    Tiny stub of FPLClient/SnapshotClient that serves data from
    in-memory dicts. You can expand it later if you add new endpoints.
    """
    def __init__(self, bootstrap, fixtures, summaries):
        self._bootstrap = bootstrap
        self._fixtures = fixtures
        self._summaries = summaries

    def bootstrap(self):
        return self._bootstrap

    def fixtures(self):
        return self._fixtures

    def element_summary(self, element_id: int):
        return self._summaries.get(element_id, {"history": []})


@pytest.fixture
def tiny_league():
    """
    Build a tiny, deterministic league with:
      - 2 teams (IDs 1 home club, 2 away club)
      - 2 players: a DEF on team 1, a FWD on team 1
      - A single upcoming GW=2 fixture: team1 (H) vs team2 (A)
      - Reasonable team strength numbers
      - Simple player histories to drive minutes & points
    """
    teams = [
        {
            "id": 1, "name": "Home FC", "short_name": "HOM",
            "strength_attack_home": 1250, "strength_attack_away": 1200,
            "strength_defence_home": 1250, "strength_defence_away": 1200,
        },
        {
            "id": 2, "name": "Away FC", "short_name": "AWY",
            "strength_attack_home": 1300, "strength_attack_away": 1280,
            "strength_defence_home": 1300, "strength_defence_away": 1280,
        },
    ]

    # Events: GW1 finished, GW2 next/current
    events = [
        {"id": 1, "is_finished": True, "is_previous": True},
        {"id": 2, "is_current": True, "is_next": True},
        {"id": 3, "is_next": False},
    ]

    # Elements / players (minimal fields we use)
    #  id, web_name, element_type (1 GK, 2 DEF, 3 MID, 4 FWD), team, now_cost
    elements = [
        {"id": 101, "web_name": "SolidDef", "element_type": 2, "team": 1, "now_cost": 45},
        {"id": 102, "web_name": "HotStrk", "element_type": 4, "team": 1, "now_cost": 70},
        {"id": 201, "web_name": "BenchGK", "element_type": 1, "team": 1, "now_cost": 40},
        {"id": 202, "web_name": "AltDef",  "element_type": 2, "team": 2, "now_cost": 45},
        {"id": 203, "web_name": "AltFwd",  "element_type": 4, "team": 2, "now_cost": 65},
    ]

    bootstrap = {"events": events, "teams": teams, "elements": elements}

    # One upcoming fixture in GW2: team1 (H) vs team2 (A)
    fixtures = [
        {
            "id": 9001, "event": 2,
            "team_h": 1, "team_a": 2,
            "team_h_difficulty": 3, "team_a_difficulty": 3,
        }
    ]

    # Histories: recent appearances & points; helps minutes + rpPA
    summaries = {
        101: {"history": [  # DEF – plays a lot, modest points
            {"minutes": 90, "total_points": 2},
            {"minutes": 90, "total_points": 6},
            {"minutes": 90, "total_points": 2},
            {"minutes": 90, "total_points": 1},
        ]},
        102: {"history": [  # FWD – plays most, some returns
            {"minutes": 28, "total_points": 0},
            {"minutes": 90, "total_points": 6},
            {"minutes": 72, "total_points": 5},
            {"minutes": 90, "total_points": 2},
        ]},
        201: {"history": [  # GK – bench type, few mins
            {"minutes": 0, "total_points": 0},
            {"minutes": 0, "total_points": 0},
            {"minutes": 0, "total_points": 0},
        ]},
        202: {"history": [  # alt DEF
            {"minutes": 90, "total_points": 1},
            {"minutes": 90, "total_points": 2},
            {"minutes": 90, "total_points": 6},
        ]},
        203: {"history": [  # alt FWD
            {"minutes": 90, "total_points": 2},
            {"minutes": 60, "total_points": 5},
            {"minutes": 78, "total_points": 6},
        ]},
    }

    client = FakeClient(bootstrap, fixtures, summaries)

    return SimpleNamespace(
        client=client,
        bootstrap=bootstrap,
        fixtures=fixtures,
        teams=teams,
        elements=elements,
        summaries=summaries,
    )
