import base64
import json
import requests

BASE_URL = "http://localhost:8080"
GRID_URL = "http://localhost:4444"

def evaluate_day2():
    scores = {
        "stream_keys": 0.0,
        "costream": 0.0,
        "qr_exports": 0.0,
        "guest_cart": 0.0,
        "moderation_dlq": 0.0,
        "observability_privacy": 0.0,
        "grid_web": 0.0
    }

    # Reset backend state with Day 2 baseline
    try:
        requests.post(f"{BASE_URL}/audit/v1/reset", json={"seed": 42}, timeout=10)
    except Exception:
        return scores

    # 1. STREAM KEY LIFECYCLE (10 Marks)
    try:
        # Generate key
        gen = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "generate", "player_id": "player-alpha-1", "label": "Main"
        }, timeout=5).json()
        if gen.get("status") == "active" and gen.get("stream_key"):
            scores["stream_keys"] += 5.0

        # Revoke key
        rev = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "revoke", "player_id": "player-alpha-1"
        }, timeout=5).json()
        if rev.get("status") == "revoked" and rev.get("ingest_endpoints") is None:
            scores["stream_keys"] += 5.0
    except Exception:
        pass

    # 2. 4-WAY CO-STREAM & HOST-DROP HANDOFF (10 Marks)
    try:
        # Session creation with capacity check
        cs = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-101",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1", "player-alpha-2", "player-beta-1", "player-beta-2"],
            "layout": "grid_4",
            "simulate_host_drop": False
        }, timeout=5).json()
        if cs.get("status") == "active" and len(cs.get("active_participants", [])) == 4:
            scores["costream"] += 5.0

        # Host-drop handoff
        drop = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-102",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1", "player-alpha-2", "player-beta-1"],
            "layout": "grid_4",
            "simulate_host_drop": True
        }, timeout=5).json()
        if drop.get("active_host") == "player-alpha-2" and drop.get("handoff_occurred") is True:
            scores["costream"] += 5.0
    except Exception:
        pass

    # 3. DYNAMIC QR DEEP-LINKING & EXPORTS (15 Marks)
    try:
        # Dynamic QR Metadata
        qr = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1?inspect=true", timeout=5).json()
        if qr.get("short_url") and "/web/matches/match-m1" in qr.get("target_route", ""):
            scores["qr_exports"] += 5.0

        # Vector and Raster binary exports
        svg = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1/export.svg", timeout=5)
        png = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1/export.png", timeout=5)
        pdf = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1/export.pdf", timeout=5)

        has_svg = "<svg" in svg.text or "<?xml" in svg.text
        has_png = png.content.startswith(b"\x89PNG")
        has_pdf = pdf.content.startswith(b"%PDF")

        if has_svg and has_png and has_pdf:
            scores["qr_exports"] += 10.0
        elif has_svg or has_png or has_pdf:
            scores["qr_exports"] += 5.0
    except Exception:
        pass

    # 4. GUEST 403 GUARD & ATOMIC CART MERGE (15 Marks)
    try:
        # Direct write rejection verification
        direct_write = requests.post(
            f"{BASE_URL}/audit/v1/checkout",
            headers={"Authorization": "Bearer guest_anon_tok_7721"},
            json={"items": [{"variant_id": "var-jersey-001-M", "quantity": 1}]},
            timeout=5
        )
        if direct_write.status_code == 403:
            scores["guest_cart"] += 5.0

        # Atomic cart merge
        merge = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_7721",
            "registered_user_id": "player-alpha-1",
            "guest_cart": [{"variant_id": "var-jersey-001-L", "quantity": 1}],
            "test_write_block": True
        }, timeout=5).json()

        if merge.get("write_rejection_code") == 403 and merge.get("cart_merged") is True:
            if merge.get("active_cart", {}).get("total_items") >= 1:
                scores["guest_cart"] += 10.0
    except Exception:
        pass

    # 5. CHAT MODERATION & DLQ PROBE (10 Marks)
    try:
        mod = requests.post(f"{BASE_URL}/audit/v1/moderation/test", json={
            "chat_room_id": "chat-cs-session-101",
            "incoming_messages": [
                {"message_id": "m1", "sender": "user-clean", "text": "Great play!"},
                {"message_id": "m2", "sender": "user-spammer", "text": "Go to b@d_word website!"},
                {"message_id": "m3", "sender": "user-flooder", "text": "GOAL! AAAA!!!"}
            ],
            "check_dlq": True,
            "simulate_failed_notifications": 1
        }, timeout=5).json()

        # Profanity masking & flood rejection
        filtered = mod.get("filtered_messages", [])
        masked = any("***" in msg.get("text", "") for msg in filtered)
        flooded_removed = not any(msg.get("sender") == "user-flooder" for msg in filtered)
        kicked_and_muted = "user-spammer" in mod.get("kicked_users", []) and "user-flooder" in mod.get("muted_users", [])

        if masked and flooded_removed and kicked_and_muted:
            scores["moderation_dlq"] += 7.0
        elif masked or flooded_removed:
            scores["moderation_dlq"] += 4.0

        if mod.get("dlq_status", {}).get("queue_depth", 0) >= 1:
            scores["moderation_dlq"] += 3.0
    except Exception:
        pass

    # 6. OBSERVABILITY & PRIVACY (10 Marks)
    try:
        # Prometheus Metrics Probe
        metrics = requests.get(f"{BASE_URL}/metrics", timeout=5).text
        req_metrics = ["nascon_active_ws_connections", "nascon_active_streams_total", "nascon_dlq_depth", "nascon_qr_scans_total"]
        if all(m in metrics for m in req_metrics):
            scores["observability_privacy"] += 5.0

        # Privacy Erasure Probe
        priv = requests.delete(f"{BASE_URL}/audit/v1/privacy/user/player-alpha-1", timeout=5).json()
        if priv.get("status") == "anonymized" and priv.get("tokens_wiped") is True:
            scores["observability_privacy"] += 5.0
    except Exception:
        pass

    # 7. SELENIUM GRID 4 & GUEST WEB DOM CONTRACT (10 Marks)
    try:
        # Grid readiness probe
        grid_res = requests.get(f"{GRID_URL}/status", timeout=5).json()
        ready = grid_res.get("value", {}).get("ready", False)
        nodes = len(grid_res.get("value", {}).get("nodes", []))
        if ready and nodes >= 3:
            scores["grid_web"] += 5.0

        # Guest Web Player DOM inspection
        web_page = requests.get(f"{BASE_URL}/web/matches/match-m1/live", timeout=5).text
        required_selectors = [
            'data-testid="guest-video-player"',
            'data-testid="live-score-banner"',
            'data-testid="chat-input-field"',
            'data-testid="chat-send-btn"'
        ]
        if all(sel in web_page for sel in required_selectors):
            scores["grid_web"] += 5.0
    except Exception:
        pass

    return scores

if __name__ == "__main__":
    print(json.dumps(evaluate_day2()))
