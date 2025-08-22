import json, os
import requests
from typing import Dict, Any, List, Optional

API = "https://fantasy.premierleague.com/api"

class FPLClient:
    def __init__(self, session=None, auth_header=None, user_agent=None, referer=None):
        self.sess = session or requests.Session()
        self.auth_header = auth_header or ""
        self.user_agent = user_agent or "Mozilla/5.0"
        self.referer = referer or "https://fantasy.premierleague.com/"

    def bootstrap(self) -> Dict[str, Any]:
        return self._get_json(f"{API}/bootstrap-static/")

    def entry(self, team_id: int) -> Dict[str, Any]:
        return self._get_json(f"{API}/entry/{team_id}/")

    def entry_picks(self, team_id: int, event: int) -> Dict[str, Any]:
        return self._get_json(f"{API}/entry/{team_id}/event/{event}/picks/")

    def element_summary(self, element_id: int) -> Dict[str, Any]:
        return self._get_json(f"{API}/element-summary/{element_id}/")

    def fixtures(self) -> List[Dict[str, Any]]:
        return self._get_json(f"{API}/fixtures/")

    def _get_json(self, url: str):
        headers = {"User-Agent": self.user_agent, "Referer": self.referer}
        if self.auth_header:
            headers["x-api-authorization"] = self.auth_header
        r = self.sess.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        return r.json()
    
    # Public endpoints
    def bootstrap(self) -> Dict[str, Any]:
        return self._get_json(f"{API}/bootstrap-static/")

    def entry(self, team_id: int) -> Dict[str, Any]:
        return self._get_json(f"{API}/entry/{team_id}/")

    def entry_picks(self, team_id: int, event: int) -> Dict[str, Any]:
        return self._get_json(f"{API}/entry/{team_id}/event/{event}/picks/")

    def element_summary(self, element_id: int) -> Dict[str, Any]:
        return self._get_json(f"{API}/element-summary/{element_id}/")

    def fixtures(self) -> List[Dict[str, Any]]:
        return self._get_json(f"{API}/fixtures/")

    # Private (requires auth_header)
    def me(self) -> Dict[str, Any]:
        return self._get_json(f"{API}/me/")

    def my_team(self, team_id: int) -> Dict[str, Any]:
        return self._get_json(f"{API}/my-team/{team_id}/")

class SnapshotClient:
    """Offline client that reads JSON files from a local directory:
    - bootstrap-static.json
    - fixtures.json
    - entry.json
    - picks.json
    - element_summaries/<id>.json (optional)
    """
    def __init__(self, snapshot_dir: str):
        self.dir = snapshot_dir

    def bootstrap(self) -> Dict[str, Any]:
        return self._load("bootstrap-static.json")

    def entry(self, team_id: int) -> Dict[str, Any]:
        return self._load("entry.json")

    def entry_picks(self, team_id: int, event: int) -> Dict[str, Any]:
        return self._load("picks.json")

    def element_summary(self, element_id: int) -> Dict[str, Any]:
        p = os.path.join(self.dir, "element_summaries", f"{element_id}.json")
        if os.path.exists(p):
            return self._load(os.path.join("element_summaries", f"{element_id}.json"))
        return {"history": [{"minutes":90,"total_points":6},{"minutes":90,"total_points":2},{"minutes":75,"total_points":5},{"minutes":30,"total_points":1}]}

    def fixtures(self) -> List[Dict[str, Any]]:
        return self._load("fixtures.json")

    def _load(self, name: str):
        with open(os.path.join(self.dir, name), "r") as f:
            return json.load(f)
