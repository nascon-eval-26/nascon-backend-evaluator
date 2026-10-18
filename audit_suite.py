import base64
import concurrent.futures
import json
import re
import requests
import threading

BASE_URL = "http://localhost:8080"
GRID_URL = "http://localhost:4444"

def evaluate_day2_hard():
    scores = {
        "stream_keys": 0.0,
        "costream": 0.0,
        "qr_exports": 0.0,
        "guest_cart": 0.0,
        "moderation_dlq": 0.0,
        "observability_privacy": 0.0,
        "grid_web": 0.0
    }

    # =========================================================================
    # 0. RESET STATE & BASELINE SEED VERIFICATION
    # =========================================================================
    try:
        r = requests.post(f"{BASE_URL}/audit/v1/reset", json={"seed": 42}, timeout=10)
        if r.status_code != 200:
            return scores
    except Exception:
        return scores

    # =========================================================================
    # 1. STREAM KEY LIFECYCLE (Max 10 Marks)
    # =========================================================================
    try:
        # 1.1 Generate key + format validation (2.5 pts)
        gen = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "generate", "player_id": "player-alpha-1", "label": "Main-Feed"
        }, timeout=5).json()
        k1 = gen.get("stream_key", "")
        if gen.get("status") == "active" and k1.startswith("sk_live_") and gen.get("ingest_endpoints", {}).get("rtmp"):
            scores["stream_keys"] += 2.5

        # 1.2 Rotate key: produces a new key with status active (2.5 pts)
        rot = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "rotate", "player_id": "player-alpha-1", "label": "Rotated"
        }, timeout=5).json()
        k2 = rot.get("stream_key", "")
        if rot.get("status") == "active" and k2 and k2 != k1:
            scores["stream_keys"] += 2.5

        # 1.3 Revoke key: null endpoints and status revoked (2.0 pts)
        rev = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "revoke", "player_id": "player-alpha-1"
        }, timeout=5).json()
        if rev.get("status") == "revoked" and rev.get("ingest_endpoints") is None and rev.get("playback_url") is None:
            scores["stream_keys"] += 2.0

        # 1.4 Strict Negative checks: Invalid action -> 400 (1.5 pts)
        bad_action = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "invalid_operation_test", "player_id": "player-alpha-1"
        }, timeout=5)
        if bad_action.status_code == 400:
            scores["stream_keys"] += 1.5

        # 1.5 Strict Negative checks: Non-existent player -> 404 (1.5 pts)
        bad_player = requests.post(f"{BASE_URL}/audit/v1/stream/key", json={
            "action": "generate", "player_id": "player-ghost-unknown"
        }, timeout=5)
        if bad_player.status_code == 404:
            scores["stream_keys"] += 1.5
    except Exception:
        pass

    # =========================================================================
    # 2. 4-WAY CO-STREAM & HANDOFF STATE MACHINE (Max 12 Marks)
    # =========================================================================
    try:
        # 2.1 Standard 4-way setup (2.5 pts)
        s1 = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-h1",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1", "player-alpha-2", "player-beta-1", "player-beta-2"],
            "layout": "grid_4",
            "simulate_host_drop": False
        }, timeout=5).json()
        if s1.get("status") == "active" and s1.get("active_host") == "player-alpha-1" and len(s1.get("active_participants", [])) == 4:
            scores["costream"] += 2.5

        # 2.2 Host-drop handoff: host drops, second player promoted, handoff_occurred: true (3.0 pts)
        s2 = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-h2",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1", "player-alpha-2", "player-beta-1"],
            "layout": "grid_4",
            "simulate_host_drop": True
        }, timeout=5).json()
        if s2.get("active_host") == "player-alpha-2" and s2.get("handoff_occurred") is True and s2.get("participant_count") == 2:
            scores["costream"] += 3.0

        # 2.3 Single host-drop termination: status terminated, active_host null (2.0 pts)
        s3 = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-h3",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1"],
            "layout": "solo",
            "simulate_host_drop": True
        }, timeout=5).json()
        if s3.get("status") == "terminated" and s3.get("active_host") is None and s3.get("participant_count") == 0:
            scores["costream"] += 2.0

        # 2.4 Strict: Overcapacity check (>4 participants -> 409 COSTREAM_SESSION_FULL) (1.5 pts)
        s_over = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-over",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1", "player-alpha-2", "player-beta-1", "player-beta-2", "player-beta-2"],
            "layout": "grid_4"
        }, timeout=5)
        if s_over.status_code == 409:
            scores["costream"] += 1.5

        # 2.5 Strict: Layout mismatch (solo with 2 players -> 400 UNSUPPORTED_LAYOUT) (1.5 pts)
        s_badlayout = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-layout",
            "host_player_id": "player-alpha-1",
            "participants": ["player-alpha-1", "player-alpha-2"],
            "layout": "solo"
        }, timeout=5)
        if s_badlayout.status_code == 400:
            scores["costream"] += 1.5

        # 2.6 Strict: Host ID not present in participants -> 400 (1.5 pts)
        s_badhost = requests.post(f"{BASE_URL}/audit/v1/costream/session", json={
            "session_id": "cs-session-badhost",
            "host_player_id": "player-beta-2",
            "participants": ["player-alpha-1", "player-alpha-2"],
            "layout": "grid_2"
        }, timeout=5)
        if s_badhost.status_code == 400:
            scores["costream"] += 1.5
    except Exception:
        pass

    # =========================================================================
    # 3. DYNAMIC QR DEEP-LINKING, REDIRECT & EXPORTS (Max 14 Marks)
    # =========================================================================
    try:
        # 3.1 Initial route metadata and deep link URI (2.0 pts)
        qr1 = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1?inspect=true", timeout=5).json()
        if qr1.get("short_url") and "/live" in qr1.get("target_route", "") and qr1.get("deep_link_uri") == "nascon://entity/match-m1":
            scores["qr_exports"] += 2.0

        # 3.2 Telemetry: calling without inspect increments scan_count; with inspect does not (2.5 pts)
        c0 = qr1.get("scan_count", 0)
        requests.get(f"{BASE_URL}/audit/v1/qr/match-m1", timeout=5) # should increment
        qr2 = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1?inspect=true", timeout=5).json() # should read without increment
        if qr2.get("scan_count", 0) == c0 + 1:
            scores["qr_exports"] += 2.5

        # 3.3 Dynamic Target Mutation on Match End Event (3.5 pts)
        # Append match_end event to match-m1 -> target route MUST switch to /vod
        requests.post(f"{BASE_URL}/audit/v1/events", json={
            "event_id": "evt-end-match-m1", "match_id": "match-m1", "type": "match_end", "payload": {}
        }, timeout=5)
        qr3 = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1?inspect=true", timeout=5).json()
        if "/vod" in qr3.get("target_route", "") and qr3.get("short_url") == qr1.get("short_url"):
            scores["qr_exports"] += 3.5

        # 3.4 Public Short Link HTTP 302 Redirection (2.0 pts)
        redir = requests.get(f"{BASE_URL}/q/m1-live", allow_redirects=False, timeout=5)
        if redir.status_code in [301, 302, 307, 308] and "/web/matches/match-m1" in redir.headers.get("Location", ""):
            scores["qr_exports"] += 2.0

        # 3.5 Vector & Raster Binary Exports (3.0 pts)
        svg = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1/export.svg", timeout=5)
        png = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1/export.png", timeout=5)
        pdf = requests.get(f"{BASE_URL}/audit/v1/qr/match-m1/export.pdf", timeout=5)

        has_svg = ("<svg" in svg.text or "<?xml" in svg.text) and "image/svg" in svg.headers.get("Content-Type", "")
        has_png = png.content.startswith(b"\x89PNG") and "image/png" in png.headers.get("Content-Type", "")
        has_pdf = pdf.content.startswith(b"%PDF") and "application/pdf" in pdf.headers.get("Content-Type", "")

        if has_svg and has_png and has_pdf:
            scores["qr_exports"] += 3.0
        elif has_svg or has_png or has_pdf:
            scores["qr_exports"] += 1.0

        # 3.6 Non-existent entity -> 404 QR_NOT_FOUND (1.0 pt)
        bad_qr = requests.get(f"{BASE_URL}/audit/v1/qr/entity-fake-missing", timeout=5)
        if bad_qr.status_code == 404:
            scores["qr_exports"] += 1.0
    except Exception:
        pass

    # =========================================================================
    # 4. GUEST 403 BOUNDARY & PROGRESSIVE CART MERGE (Max 14 Marks)
    # =========================================================================
    try:
        # 4.1 Direct write rejection with 403 GUEST_WRITE_FORBIDDEN on 2 routes (3.0 pts)
        w1 = requests.post(f"{BASE_URL}/audit/v1/checkout", headers={"Authorization": "Bearer guest_anon_tok_7721"}, json={"items": []}, timeout=5)
        w2 = requests.post(f"{BASE_URL}/audit/v1/events", headers={"Authorization": "Bearer guest_anon_tok_7721"}, json={}, timeout=5)
        if w1.status_code == 403 and w2.status_code == 403:
            scores["guest_cart"] += 3.0

        # 4.2 Standard valid cart merge (3.0 pts)
        m1 = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_7721",
            "registered_user_id": "player-alpha-1",
            "guest_cart": [{"variant_id": "var-jersey-001-L", "quantity": 1}],
            "test_write_block": True
        }, timeout=5).json()

        if m1.get("cart_merged") is True and m1.get("write_rejection_code") == 403 and m1.get("active_cart", {}).get("total_items") == 1:
            scores["guest_cart"] += 3.0

        # 4.3 KILLER TEST: Network Migration Replay Idempotency (3.0 pts)
        # Replaying identical request MUST return 200 without double-adding items (total_items remains 1, not 2)
        m1_replay = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_7721",
            "registered_user_id": "player-alpha-1",
            "guest_cart": [{"variant_id": "var-jersey-001-L", "quantity": 1}],
            "test_write_block": True
        }, timeout=5).json()
        if m1_replay.get("active_cart", {}).get("total_items") == 1:
            scores["guest_cart"] += 3.0

        # 4.4 Reusing already merged guest_token with different user -> 409 (2.0 pts)
        m_reused = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_7721",
            "registered_user_id": "player-alpha-2",
            "guest_cart": [{"variant_id": "var-jersey-001-L", "quantity": 1}],
            "test_write_block": False
        }, timeout=5)
        if m_reused.status_code == 409:
            scores["guest_cart"] += 2.0

        # 4.5 Excess stock requested -> 409 OUT_OF_STOCK (1.5 pts)
        m_over = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_new_111",
            "registered_user_id": "player-alpha-1",
            "guest_cart": [{"variant_id": "var-jersey-001-M", "quantity": 99999}],
            "test_write_block": False
        }, timeout=5)
        if m_over.status_code == 409:
            scores["guest_cart"] += 1.5

        # 4.6 Non-existent variant -> 404 VARIANT_NOT_FOUND (1.5 pts)
        m_badvar = requests.post(f"{BASE_URL}/audit/v1/guest/cart-merge", json={
            "guest_token": "guest_anon_tok_new_222",
            "registered_user_id": "player-alpha-1",
            "guest_cart": [{"variant_id": "var-nonexistent-999", "quantity": 1}],
            "test_write_block": False
        }, timeout=5)
        if m_badvar.status_code == 404:
            scores["guest_cart"] += 1.5
    except Exception:
        pass

    # =========================================================================
    # 5. CHAT MODERATION & NOTIFICATION DLQ (Max 12 Marks)
    # =========================================================================
    try:
        # 5.1 Deep Leetspeak Obfuscation Masking (3.0 pts)
        mod1 = requests.post(f"{BASE_URL}/audit/v1/moderation/test", json={
            "chat_room_id": "chat-cs-session-101",
            "incoming_messages": [
                {"message_id": "msg-1", "sender": "user-ok", "text": "Clean sports commentary"},
                {"message_id": "msg-2", "sender": "user-bad", "text": "Watch this p.0.r.n and s!c@m a$$h0le"}
            ],
            "check_dlq": False,
            "simulate_failed_notifications": 0
        }, timeout=5).json()

        f_msgs = mod1.get("filtered_messages", [])
        m2_text = next((m.get("text", "") for m in f_msgs if m.get("message_id") == "msg-2"), "")
        if "***" in m2_text and "p.0.r.n" not in m2_text:
            scores["moderation_dlq"] += 3.0

        # 5.2 Offender Discipline: Profanity sender in kicked_users (2.0 pts)
        if "user-bad" in mod1.get("kicked_users", []):
            scores["moderation_dlq"] += 2.0

        # 5.3 Character & Punctuation Flooding: Dropped from broadcast + muted (2.5 pts)
        mod2 = requests.post(f"{BASE_URL}/audit/v1/moderation/test", json={
            "chat_room_id": "chat-cs-session-101",
            "incoming_messages": [
                {"message_id": "msg-3", "sender": "user-flooder", "text": "GOALLLLLLLLL!!!"}
            ],
            "check_dlq": False,
            "simulate_failed_notifications": 0
        }, timeout=5).json()

        f_msgs2 = mod2.get("filtered_messages", [])
        flooded_dropped = not any(m.get("sender") == "user-flooder" for m in f_msgs2)
        flooder_muted = "user-flooder" in mod2.get("muted_users", [])
        if flooded_dropped and flooder_muted:
            scores["moderation_dlq"] += 2.5

        # 5.4 Dead-Letter Queue (DLQ) depth tracking (2.5 pts)
        mod3 = requests.post(f"{BASE_URL}/audit/v1/moderation/test", json={
            "chat_room_id": "chat-cs-session-101",
            "incoming_messages": [],
            "check_dlq": True,
            "simulate_failed_notifications": 3
        }, timeout=5).json()
        if mod3.get("dlq_status", {}).get("queue_depth", 0) >= 3:
            scores["moderation_dlq"] += 2.5

        # 5.5 KILLER TEST: Concurrent Moderation Call Deduplication (2.0 pts)
        barrier = threading.Barrier(10)
        def send_spam(idx):
            barrier.wait()
            return requests.post(f"{BASE_URL}/audit/v1/moderation/test", json={
                "chat_room_id": "chat-cs-session-101",
                "incoming_messages": [{"message_id": f"race-{idx}", "sender": "repeat-spammer", "text": "b@d_word"}],
                "check_dlq": False
            }, timeout=5)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            race_res = list(ex.map(send_spam, range(10)))

        all_200 = all(r.status_code == 200 for r in race_res)
        last_kicked = race_res[-1].json().get("kicked_users", []) if all_200 else []
        # Must contain repeat-spammer and have zero duplicate entries
        if all_200 and "repeat-spammer" in last_kicked and len(last_kicked) == len(set(last_kicked)):
            scores["moderation_dlq"] += 2.0
    except Exception:
        pass

    # =========================================================================
    # 6. OBSERVABILITY & PRIVACY ERASURE (Max 8 Marks)
    # =========================================================================
    try:
        # 6.1 Prometheus /metrics probe with all 5 mandatory metrics (4.0 pts)
        met = requests.get(f"{BASE_URL}/metrics", timeout=5).text
        req_metrics = [
            "nascon_active_ws_connections",
            "nascon_active_streams_total",
            "nascon_stream_bitrate_kbps",
            "nascon_dlq_depth",
            "nascon_qr_scans_total"
        ]
        found_count = sum(1 for m in req_metrics if m in met)
        scores["observability_privacy"] += round((found_count / 5.0) * 4.0, 2)

        # 6.2 Privacy Erasure Probe (4.0 pts)
        priv = requests.delete(f"{BASE_URL}/audit/v1/privacy/user/player-alpha-1", timeout=5).json()
        if priv.get("status") == "anonymized" and priv.get("pii_retained") is False and priv.get("tokens_wiped") is True:
            scores["observability_privacy"] += 4.0
    except Exception:
        pass

    # =========================================================================
    # 7. SELENIUM GRID 4 & GUEST WEB DOM CONTRACT (Max 10 Marks)
    # =========================================================================
    try:
        # 7.1 Selenium Grid 4 cluster status: ready: true, nodes >= 3 (4.0 pts)
        grid = requests.get(f"{GRID_URL}/status", timeout=5).json()
        if grid.get("value", {}).get("ready") is True and len(grid.get("value", {}).get("nodes", [])) >= 3:
            scores["grid_web"] += 4.0

        # 7.2 Guest Web DOM Contract: Proportional check for all 9 data-testid attributes (6.0 pts)
        web_html = requests.get(f"{BASE_URL}/web/matches/match-m1/live", timeout=5).text
        selectors = [
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
        matched_sel = sum(1 for s in selectors if s in web_html)
        scores["grid_web"] += round((matched_sel / 9.0) * 6.0, 2)
    except Exception:
        pass

    return scores

if __name__ == "__main__":
    print(json.dumps(evaluate_day2_hard()))
