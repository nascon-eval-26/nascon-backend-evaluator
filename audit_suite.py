import base64
import concurrent.futures
import json
import requests
import threading

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

    # 0. RESET STATE
    try:
        r = requests.post(f"{BASE_URL}/audit/v1/reset", json={"seed": 42}, timeout=10)
        if r.status_code != 200:
            return scores
    except Exception:
        return scores

    # =========================================================================
    # 1. STREAM KEY LIFECYCLE (10 Marks)
    # =========================================================================
    try:
        # Happy Path: Generate & Revoke (4 pts)
        gen = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "generate", "player_id": "player-alpha-1", "label": "Main"
        }, timeout=5).json()
        k1 = gen.get("stream_key")

        rev = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "revoke", "player_id": "player-alpha-1"
        }, timeout=5).json()

        if gen.get("status") == "active" and k1 and rev.get("status") == "revoked" and rev.get("ingest_endpoints") is None:
            scores["stream_keys"] += 4.0

        # Strict: Revoked key usage yields 409 KEY_REVOKED (3 pts)
        post_rev = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "revoke", "player_id": "player-alpha-1"
        }, timeout=5)
        if post_rev.status_code in [404, 409]:
            scores["stream_keys"] += 3.0

        # Strict: Validation rejection (invalid action -> 400, unknown player -> 404) (3 pts)
        bad_act = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "invalid_action_xyz", "player_id": "player-alpha-1"
        }, timeout=5)
        bad_plr = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "generate", "player_id": "player-non-existent-999"
        }, timeout=5)
        if bad_act.status_code == 400 and bad_plr.status_code == 404:
            scores["stream_keys"] += 3.0
    except Exception:
        pass

    # =========================================================================
    # 2. 4-WAY CO-STREAM & HOST-DROP HANDOFF (10 Marks)
    # =========================================================================
    try:
        # Happy Path: Standard 4-way & Handoff (4 pts)
        drop = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-101",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1", "player-alpha-2", "player-beta-1", "player-beta-2"],
            "layout": "grid_4",
            "simulate_host_drop": True
        }, timeout=5).json()
        if drop.get("active_host") == "player-alpha-2" and drop.get("handoff_occurred") is True and drop.get("participant_count") == 3:
            scores["costream"] += 4.0

        # Strict: Overcapacity check (>4 participants -> 409 COSTREAM_SESSION_FULL) (2 pts)
        over = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-over",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1", "player-alpha-2", "player-beta-1", "player-beta-2", "player-beta-2"],
            "layout": "grid_4",
            "simulate_host_drop": False
        }, timeout=5)
        if over.status_code == 409:
            scores["costream"] += 2.0

        # Strict: Layout capacity mismatch (solo layout with 2 participants -> 400) (2 pts)
        bad_layout = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-layout",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1", "player-alpha-2"],
            "layout": "solo",
            "simulate_host_drop": False
        }, timeout=5)
        if bad_layout.status_code == 400:
            scores["costream"] += 2.0

        # Strict: Single participant host-drop -> status: terminated, active_host: null (2 pts)
        term = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-single",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1"],
            "layout": "solo",
            "simulate_host_drop": True
        }, timeout=5).json()
        if term.get("status") == "terminated" and term.get("active_host") is None:
            scores["costream"] += 2.0
    except Exception:
        pass

    # =========================================================================
    # 3. DYNAMIC QR DEEP-LINKING & EXPORTS (15 Marks)
    # =========================================================================
    try:
        # Happy Path: Metadata & All 3 Export Magic Headers (6 pts)
        qr_pre = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1?inspect=true", timeout=5).json()
        svg = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1/export.svg", timeout=5)
        png = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1/export.png", timeout=5)
        pdf = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1/export.pdf", timeout=5)

        has_svg = "<svg" in svg.text or "<?xml" in svg.text
        has_png = png.content.startswith(b"\x89PNG")
        has_pdf = pdf.content.startswith(b"%PDF")

        if qr_pre.get("short_url") and has_svg and has_png and has_pdf:
            scores["qr_exports"] += 6.0
        elif has_svg or has_png or has_pdf:
            scores["qr_exports"] += 3.0

        # KILLER TEST: Dynamic Target Mutation on Match State Change (6 pts)
        # 1. match-m1 starts as in_progress -> route is /web/matches/match-m1/live
        # 2. Append match_end event -> status becomes completed
        # 3. Target route MUST update dynamically to /web/matches/match-m1/vod
        requests.post(f"{BASE_URL}/audit/v1/events", json={
            "event_id": "evt-end-m1", "match_id": "match-m1", "type": "match_end", "payload": {}
        }, timeout=5)

        qr_post = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1?inspect=true", timeout=5).json()
        if "/vod" in qr_post.get("target_route", "") and qr_post.get("short_url") == qr_pre.get("short_url"):
            scores["qr_exports"] += 6.0

        # Strict: 404 for unknown QR entity (3 pts)
        bad_qr = requests.get(f"{BASE_URL}/audit/v1/qr/entity-unknown-12345", timeout=5)
        if bad_qr.status_code == 404:
            scores["qr_exports"] += 3.0
    except Exception:
        pass

    # =========================================================================
    # 4. GUEST 403 GUARD & ATOMIC CART MERGE (15 Marks)
    # =========================================================================
    try:
        # Strict: Direct write protection across multiple endpoints (4 pts)
        w1 = requests.post(f"{BASE_URL}/audit/v1/checkout", headers={"Authorization": "Bearer guest_anon_tok_7721"}, json={"items": []}, timeout=5)
        w2 = requests.post(f"{BASE_URL}/audit/v1/events", headers={"Authorization": "Bearer guest_anon_tok_7721"}, json={}, timeout=5)
        if w1.status_code == 403 and w2.status_code == 403:
            scores["guest_cart"] += 4.0

        # Happy Path: Valid Cart Merge (3 pts)
        merge1 = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_7721",
            "registered_user_id": "player-alpha-1",
            "guest_cart": [{"variant_id": "var-jersey-001-L", "quantity": 1}],
            "test_write_block": True
        }, timeout=5).json()
        if merge1.get("cart_merged") is True and merge1.get("write_rejection_code") == 403:
            scores["guest_cart"] += 3.0

        # KILLER TEST: Network Migration Replay Idempotency (3 pts)
        # Replaying exact request must return 200 without double-adding items
        merge_replay = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_7721",
            "registered_user_id": "player-alpha-1",
            "guest_cart": [{"variant_id": "var-jersey-001-L", "quantity": 1}],
            "test_write_block": True
        }, timeout=5).json()
        if merge_replay.get("active_cart", {}).get("total_items") == 1:
            scores["guest_cart"] += 3.0

        # Strict: Token Re-use for different user -> 409 GUEST_TOKEN_ALREADY_MERGED (3 pts)
        reused = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_7721",
            "registered_user_id": "player-alpha-2",
            "guest_cart": [{"variant_id": "var-jersey-001-L", "quantity": 1}],
            "test_write_block": False
        }, timeout=5)
        if reused.status_code == 409:
            scores["guest_cart"] += 3.0

        # Strict: Exceeding available stock -> 409 OUT_OF_STOCK (2 pts)
        over_stock = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_new_8899",
            "registered_user_id": "player-alpha-1",
            "guest_cart": [{"variant_id": "var-jersey-001-M", "quantity": 9999}],
            "test_write_block": False
        }, timeout=5)
        if over_stock.status_code == 409:
            scores["guest_cart"] += 2.0
    except Exception:
        pass

    # =========================================================================
    # 5. CHAT MODERATION & DLQ PROBE (10 Marks)
    # =========================================================================
    try:
        # Happy Path: Deep Leetspeak & Flood Detection (4 pts)
        mod = requests.post(f"{BASE_URL}/audit/v1/moderation/test", json={
            "chat_room_id": "chat-cs-session-101",
            "incoming_messages": [
                {"message_id": "m1", "sender": "user-clean", "text": "Clean msg"},
                {"message_id": "m2", "sender": "user-spammer", "text": "Visit p.0.r.n and s!c@m a$$h0le"},
                {"message_id": "m3", "sender": "user-flooder-1", "text": "WHAT?????"},
                {"message_id": "m4", "sender": "user-flooder-2", "text": "GOALLLLLLLLL"}
            ],
            "check_dlq": True,
            "simulate_failed_notifications": 2
        }, timeout=5).json()

        filtered = mod.get("filtered_messages", [])
        has_masked = any("***" in msg.get("text", "") for msg in filtered)
        flooders_dropped = not any(msg.get("sender") in ["user-flooder-1", "user-flooder-2"] for msg in filtered)
        users_muted = "user-flooder-1" in mod.get("muted_users", [])

        if has_masked and flooders_dropped and users_muted:
            scores["moderation_dlq"] += 4.0

        # Strict: DLQ queue depth verification (2 pts)
        if mod.get("dlq_status", {}).get("queue_depth", 0) >= 2:
            scores["moderation_dlq"] += 2.0

        # KILLER TEST: 10 Concurrent Race Requests on Moderation (4 pts)
        # Deduplication check: kicked_users must not contain duplicate entries
        barrier = threading.Barrier(10)

        def fire_moderation(idx):
            barrier.wait()
            return requests.post(f"{BASE_URL}/audit/v1/moderation/test", json={
                "chat_room_id": "chat-cs-session-101",
                "incoming_messages": [
                    {"message_id": f"race-msg-{idx}", "sender": "concurrent-spammer", "text": "b@d_word link"}
                ],
                "check_dlq": False,
                "simulate_failed_notifications": 0
            }, timeout=5)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            race_responses = list(ex.map(fire_moderation, range(10)))

        all_ok = all(r.status_code == 200 for r in race_responses)
        last_body = race_responses[-1].json() if all_ok else {}
        kicked_list = last_body.get("kicked_users", [])

        # Kicked list must contain the spammer, with ZERO duplicate entries
        if all_ok and "concurrent-spammer" in kicked_list and len(kicked_list) == len(set(kicked_list)):
            scores["moderation_dlq"] += 4.0
    except Exception:
        pass

    # =========================================================================
    # 6. OBSERVABILITY & PRIVACY (10 Marks)
    # =========================================================================
    try:
        # Strict: Prometheus All 5 Metrics Present (5 pts)
        metrics = requests.get(f"{BASE_URL}/metrics", timeout=5).text
        mandatory_metrics = [
            "nascon_active_ws_connections",
            "nascon_active_streams_total",
            "nascon_stream_bitrate_kbps",
            "nascon_dlq_depth",
            "nascon_qr_scans_total"
        ]
        if all(m in metrics for m in mandatory_metrics):
            scores["observability_privacy"] += 5.0
        elif any(m in metrics for m in mandatory_metrics):
            scores["observability_privacy"] += 2.0

        # Strict: Privacy Erasure Probe (5 pts)
        priv = requests.delete(f"{BASE_URL}/audit/v1/privacy/user/player-alpha-1", timeout=5).json()
        if priv.get("status") == "anonymized" and priv.get("pii_retained") is False and priv.get("tokens_wiped") is True:
            scores["observability_privacy"] += 5.0
    except Exception:
        pass

    # =========================================================================
    # 7. SELENIUM GRID 4 & GUEST WEB DOM CONTRACT (10 Marks)
    # =========================================================================
    try:
        # Strict: Selenium Grid Cluster (ready: true, >= 3 active nodes) (4 pts)
        grid_res = requests.get(f"{GRID_URL}/status", timeout=5).json()
        is_ready = grid_res.get("value", {}).get("ready", False)
        node_count = len(grid_res.get("value", {}).get("nodes", []))
        if is_ready and node_count >= 3:
            scores["grid_web"] += 4.0

        # Strict: All 9 Mandatory data-testid DOM Selectors (6 pts)
        web_html = requests.get(f"{BASE_URL}/web/matches/match-m1/live", timeout=5).text
        required_selectors = [
            'data-testid="guest-video-player"',
            'data-testid="live-score-banner"',
            'data-testid="pinned-merch-card"',
            'data-testid="add-to-guest-cart-btn"',
            'data-testid="guest-cart-count"',
            'data-testid="chat-message-list"',
            'data-testid="chat-input-field"',
            'data-testid="chat-send-btn"',
            'data-testid="progressive-auth-modal"'
        ]
        matched = sum(1 for sel in required_selectors if sel in web_html)

        if matched == 9:
            scores["grid_web"] += 6.0
        elif matched >= 5:
            scores["grid_web"] += 3.0
    except Exception:
        pass

    return scores

if __name__ == "__main__":
    print(json.dumps(evaluate_day2()))
