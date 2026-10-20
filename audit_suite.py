import base64
import concurrent.futures
import json
import threading
import requests

BASE_URL = "http://localhost:8080"

def evaluate_submission():
    scores = {
        "fixtures": 0.0,
        "scoring": 0.0,
        "standings": 0.0,
        "store": 0.0,
        "roster": 0.0,
        "rbac": 0.0
    }

    # Reset backend state
    try:
        requests.post(f"{BASE_URL}/audit/v1/reset", json={"seed": 42}, timeout=10)
    except Exception:
        return scores

    # 1. FIXTURES & BRACKETS (6 Marks)
    try:
        # Round-robin: 5 teams, single leg
        rr = requests.post(f"{BASE_URL}/audit/v1/fixtures", json={
            "format": "round_robin", "teams": ["t1", "t2", "t3", "t4", "t5"], "params": {"legs": 1}
        }, timeout=5).json()
        if len(rr.get("rounds", [])) == 5:
            scores["fixtures"] += 2.0

        # Swiss pairing round 1
        sw = requests.post(f"{BASE_URL}/audit/v1/fixtures", json={
            "format": "swiss", "teams": ["t1", "t2", "t3", "t4"], "params": {"total_rounds": 2, "round": 1}
        }, timeout=5).json()
        if len(sw.get("pairings", [])) == 2:
            scores["fixtures"] += 2.0

        # Single elimination bracket size
        se = requests.post(f"{BASE_URL}/audit/v1/fixtures", json={
            "format": "single_elim", "teams": ["t1", "t2", "t3", "t4", "t5", "t6"], "params": {}
        }, timeout=5).json()
        if se.get("bracket_size") == 8:
            scores["fixtures"] += 2.0
    except Exception:
        pass

    # 2. SCORING & MYSTERY SPORT (6 Marks)
    try:
        # Mystery sport setup
        sp = requests.post(f"{BASE_URL}/audit/v1/sports", json={
            "sport_id": "dodgeball", "name": "Dodgeball", "scoring_model": "event",
            "periods": {"count": 2, "duration_minutes": 15},
            "scoring_events": {"tag_out": {"points": 1}},
            "draw_allowed": True, "overtime": {"policy": "none"},
            "roster": {"min_squad_size": 6, "max_squad_size": 10, "required_positions": {}}
        }, timeout=5)
        if sp.status_code == 201:
            scores["scoring"] += 2.0

        # Event stream progression
        requests.post(f"{BASE_URL}/audit/v1/events", json={
            "event_id": "e1", "match_id": "m100", "type": "match_init",
            "payload": {"sport_id": "football", "home_team_id": "t1", "away_team_id": "t2"}
        }, timeout=5)
        requests.post(f"{BASE_URL}/audit/v1/events", json={
            "event_id": "e2", "match_id": "m100", "type": "match_start", "payload": {}
        }, timeout=5)
        sc = requests.post(f"{BASE_URL}/audit/v1/events", json={
            "event_id": "e3", "match_id": "m100", "type": "score", "payload": {"team_id": "t1", "event_type": "goal"}
        }, timeout=5)
        if sc.status_code == 201:
            scores["scoring"] += 2.0

        # Compensating event rollback
        comp = requests.post(f"{BASE_URL}/audit/v1/events", json={
            "event_id": "e4", "match_id": "m100", "type": "compensation", "payload": {"compensates": "e3", "reason": "VAR"}
        }, timeout=5)
        score_view = requests.get(f"{BASE_URL}/audit/v1/score/m100", timeout=5).json()
        if comp.status_code == 201 and score_view.get("home", {}).get("score") == 0:
            scores["scoring"] += 2.0
    except Exception:
        pass

    # 3. STANDINGS ENGINE (6 Marks)
    try:
        requests.post(f"{BASE_URL}/audit/v1/leagues", json={
            "league_id": "lg-test", "sport_id": "football", "teams": ["t1", "t2"],
            "fixtures": [{"match_id": "m-lg-1", "home": "t1", "away": "t2"}],
            "qualification": {"spots": 1}
        }, timeout=5)
        requests.post(f"{BASE_URL}/audit/v1/events", json={"event_id": "el1", "match_id": "m-lg-1", "type": "match_start", "payload": {}}, timeout=5)
        requests.post(f"{BASE_URL}/audit/v1/events", json={"event_id": "el2", "match_id": "m-lg-1", "type": "score", "payload": {"team_id": "t1", "event_type": "goal"}}, timeout=5)
        requests.post(f"{BASE_URL}/audit/v1/events", json={"event_id": "el3", "match_id": "m-lg-1", "type": "match_end", "payload": {}}, timeout=5)

        st = requests.get(f"{BASE_URL}/audit/v1/standings/lg-test", timeout=5).json()
        table = st.get("table", [])
        if len(table) == 2 and table[0].get("team_id") == "t1" and table[0].get("points") == 3:
            scores["standings"] += 3.0
        if table and table[0].get("status") in ["clinched", "still_possible"]:
            scores["standings"] += 3.0
    except Exception:
        pass

    # 4. CONCURRENCY & STORE (6 Marks)
    try:
        requests.post(f"{BASE_URL}/audit/v1/reset", json={"stock": {"var-jersey-001-M": 1}}, timeout=10)
        barrier = threading.Barrier(20)

        def attempt_buy(idx):
            barrier.wait()
            return requests.post(f"{BASE_URL}/audit/v1/checkout", json={
                "order_id": f"ord-burst-{idx}", "customer_id": f"c-{idx}",
                "items": [{"variant_id": "var-jersey-001-M", "quantity": 1}],
                "payment": {"token": "tok_success"}
            }, timeout=10)

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            checkout_responses = list(executor.map(attempt_buy, range(20)))

        codes = [res.status_code for res in checkout_responses]
        if codes.count(201) == 1 and codes.count(409) == 19:
            scores["store"] += 4.0

        inv = requests.get(f"{BASE_URL}/audit/v1/inventory/var-jersey-001-M", timeout=5).json()
        successful_res = next((res.json() for res in checkout_responses if res.status_code == 201), None)
        receipt_obj = (successful_res.get("receipt") or {}) if successful_res else {}
        pdf_b64 = receipt_obj.get("pdf_base64", "")
        pdf_bytes = base64.b64decode(pdf_b64) if pdf_b64 else b""

        if inv.get("stock") == 0 and inv.get("reserved") == 0 and pdf_bytes.startswith(b"%PDF"):
            scores["store"] += 2.0
    except Exception:
        pass

    # 5. ROSTER & TRANSFERS (6 Marks)
    try:
        requests.post(f"{BASE_URL}/audit/v1/roster/setup", json={
            "league": {"league_id": "lg-r", "tenant_id": "tenant-alpha", "sport_id": "football",
                       "transfer_window": {"open": "2026-01-01", "close": "2026-12-31"}, "max_squad_size": 2},
            "squads": [{"squad_id": "sq-1", "club_id": "club-alpha-1", "tenant_id": "tenant-alpha", "name": "Squad 1"},
                       {"squad_id": "sq-2", "club_id": "club-alpha-2", "tenant_id": "tenant-alpha", "name": "Squad 2"}],
            "players": [{"player_id": "p-1", "name": "P1", "position": "gk", "squad_id": "sq-1", "role": "starter"}]
        }, timeout=5)

        tr = requests.post(f"{BASE_URL}/audit/v1/roster/transfer", json={
            "request_id": "tr-1", "league_id": "lg-r", "player_id": "p-1", "type": "transfer",
            "from_squad_id": "sq-1", "to_squad_id": "sq-2", "effective_date": "2026-06-01", "reason": "move"
        }, timeout=5)
        if tr.status_code == 201:
            scores["roster"] += 3.0

        hist = requests.get(f"{BASE_URL}/audit/v1/roster/history/p-1", timeout=5).json()
        if hist.get("current_squad_id") == "sq-2" and len(hist.get("history", [])) >= 1:
            scores["roster"] += 3.0
    except Exception:
        pass

    # 6. RBAC & SECURITY (6 Marks)
    try:
        rbac = requests.post(f"{BASE_URL}/audit/v1/rbac-matrix", timeout=5).json()
        admin_token = rbac.get("tokens", {}).get("super_admin")
        viewer_token = rbac.get("tokens", {}).get("viewer")

        p1_admin = requests.post(f"{BASE_URL}/audit/v1/rbac/tenants", headers={"Authorization": f"Bearer {admin_token}"}, json={}, timeout=5)
        p1_viewer = requests.post(f"{BASE_URL}/audit/v1/rbac/tenants", headers={"Authorization": f"Bearer {viewer_token}"}, json={}, timeout=5)

        if p1_admin.status_code == 200 and p1_viewer.status_code == 403:
            scores["rbac"] += 3.0

        f_club = rbac.get("context", {}).get("foreign_club_id", "club-beta-1")
        cross = requests.get(f"{BASE_URL}/audit/v1/rbac/clubs/{f_club}", headers={"Authorization": f"Bearer {viewer_token}"}, timeout=5)
        if cross.status_code == 403:
            scores["rbac"] += 1.5

        with requests.Session() as s:
            for _ in range(120):
                resp = s.get(f"{BASE_URL}/api/v1/ping", timeout=2)
                if resp.status_code == 429:
                    scores["rbac"] += 1.5
                    break
    except Exception:
        pass

    return scores

if __name__ == "__main__":
    print(json.dumps(evaluate_submission()))
