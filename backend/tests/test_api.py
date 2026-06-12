"""Integration tests for all REST API endpoints via FastAPI TestClient."""
import pytest

TENANT_1_ID = "22222222-0000-0000-0000-000000000001"  # Alice Johnson, Harbor North
TENANT_2_ID = "22222222-0000-0000-0000-000000000002"  # Bob Martinez, Harbor South
BLDG_1_ID   = "11111111-0000-0000-0000-000000000001"  # Harbor North
BLDG_2_ID   = "11111111-0000-0000-0000-000000000002"  # Harbor South


def post_ticket(client, urgency="routine", tenant_id=TENANT_1_ID, duration=15,
                summary="test issue", confidence=0.8, **kwargs):
    return client.post("/tickets", json={
        "tenant_id": tenant_id,
        "urgency": urgency,
        "summary": summary,
        "confidence": confidence,
        "estimated_duration_minutes": duration,
        **kwargs,
    })


# ── Buildings ──────────────────────────────────────────────────────────────────

def test_list_buildings_returns_all_eight(client):
    r = client.get("/buildings")
    assert r.status_code == 200
    assert len(r.json()) == 8


# ── Tenants ────────────────────────────────────────────────────────────────────

def test_phone_lookup_returns_correct_tenant(client):
    r = client.get("/tenants?phone=%2B14155551001")
    assert r.status_code == 200
    assert r.json()["name"] == "Alice Johnson"


def test_phone_lookup_not_found(client):
    r = client.get("/tenants?phone=%2B10000000000")
    assert r.status_code == 404


def test_name_fuzzy_match_case_insensitive(client):
    r = client.get("/tenants?name=alice")
    assert r.status_code == 200
    names = [t["name"] for t in r.json()]
    assert "Alice Johnson" in names


def test_name_fuzzy_no_results(client):
    r = client.get("/tenants?name=zzznomatch")
    assert r.status_code == 200
    assert r.json() == []


def test_unit_lookup_exact_match(client):
    r = client.get("/tenants/1A")
    assert r.status_code == 200
    assert r.json()["unit"] == "1A"


def test_unit_lookup_case_insensitive(client):
    r = client.get("/tenants/1a")
    assert r.status_code == 200
    assert r.json()["unit"] == "1A"


def test_unit_lookup_not_found(client):
    r = client.get("/tenants/99Z")
    assert r.status_code == 404


def test_tenants_no_params_returns_all(client):
    r = client.get("/tenants")
    assert r.status_code == 200
    assert len(r.json()) == 10


# ── Ticket creation ────────────────────────────────────────────────────────────

def test_create_ticket_returns_201_with_id(client):
    r = post_ticket(client, urgency="urgent", duration=30)
    assert r.status_code == 201
    data = r.json()
    assert data["id"] is not None
    assert data["status"] == "open"
    assert data["urgency"] == "urgent"


def test_create_ticket_duration_not_multiple_of_five_rejected(client):
    r = post_ticket(client, duration=17)
    assert r.status_code == 422


def test_create_ticket_duration_below_five_rejected(client):
    r = post_ticket(client, duration=0)
    assert r.status_code == 422


def test_create_ticket_confidence_out_of_range_rejected(client):
    r = post_ticket(client, confidence=1.5)
    assert r.status_code == 422


def test_create_emergency_ticket_has_null_scheduled_start(client):
    r = post_ticket(client, urgency="emergency", duration=60, confidence=0.98,
                    instructions="Turn off water main")
    assert r.status_code == 201
    assert r.json()["scheduled_start"] is None


def test_create_incomplete_ticket_accepted(client):
    r = post_ticket(client, status="incomplete")
    assert r.status_code == 201
    assert r.json()["status"] == "incomplete"


def test_create_ticket_unmatched_tenant_accepted(client):
    r = client.post("/tickets", json={
        "tenant_id": None,
        "urgency": "routine",
        "summary": "Caller not in system",
        "confidence": 0.7,
        "estimated_duration_minutes": 15,
    })
    assert r.status_code == 201
    assert r.json()["tenant_id"] is None


# ── Ticket listing & filtering ─────────────────────────────────────────────────

def test_list_tickets_initially_empty(client):
    r = client.get("/tickets")
    assert r.status_code == 200
    assert r.json() == []


def test_list_tickets_filter_by_status(client):
    post_ticket(client, urgency="urgent", duration=30)
    r = client.get("/tickets?status=open")
    assert all(t["status"] == "open" for t in r.json())
    assert len(r.json()) == 1


def test_list_tickets_filter_by_urgency(client):
    post_ticket(client, urgency="urgent", duration=30)
    post_ticket(client, urgency="routine", duration=15)
    r = client.get("/tickets?urgency=urgent")
    assert all(t["urgency"] == "urgent" for t in r.json())
    assert len(r.json()) == 1


def test_list_tickets_filter_by_building_id(client):
    post_ticket(client, urgency="routine", tenant_id=TENANT_1_ID)   # Harbor North
    post_ticket(client, urgency="routine", tenant_id=TENANT_2_ID)   # Harbor South
    r = client.get(f"/tickets?building_id={BLDG_1_ID}")
    results = r.json()
    assert len(results) == 1
    assert results[0]["tenant_id"] == TENANT_1_ID


# ── Emergency endpoint ─────────────────────────────────────────────────────────

def test_emergency_endpoint_returns_only_open_and_in_progress(client):
    open_emrg = post_ticket(client, urgency="emergency", duration=60, confidence=0.99).json()
    completed = post_ticket(client, urgency="emergency", duration=30, confidence=0.99,
                            status="completed", tenant_id=TENANT_2_ID).json()
    r = client.get("/tickets/emergency")
    ids = [t["id"] for t in r.json()]
    assert open_emrg["id"] in ids
    assert completed["id"] not in ids


def test_emergency_endpoint_empty_when_none_active(client):
    r = client.get("/tickets/emergency")
    assert r.json() == []


# ── Single ticket ──────────────────────────────────────────────────────────────

def test_get_ticket_by_id(client):
    created = post_ticket(client).json()
    r = client.get(f"/tickets/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_get_ticket_not_found(client):
    r = client.get("/tickets/does-not-exist")
    assert r.status_code == 404


# ── Ticket patch ───────────────────────────────────────────────────────────────

def test_patch_ticket_status(client):
    created = post_ticket(client, urgency="urgent", duration=30).json()
    r = client.patch(f"/tickets/{created['id']}", json={"status": "in_progress"})
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"


def test_patch_ticket_duration(client):
    created = post_ticket(client, duration=15).json()
    r = client.patch(f"/tickets/{created['id']}", json={"estimated_duration_minutes": 45})
    assert r.status_code == 200
    assert r.json()["estimated_duration_minutes"] == 45


def test_patch_ticket_invalid_duration_rejected(client):
    created = post_ticket(client, duration=15).json()
    r = client.patch(f"/tickets/{created['id']}", json={"estimated_duration_minutes": 7})
    assert r.status_code == 422


def test_patch_ticket_not_found(client):
    r = client.patch("/tickets/does-not-exist", json={"status": "completed"})
    assert r.status_code == 404


# ── Alerts ─────────────────────────────────────────────────────────────────────

def test_create_oncall_alert_returns_technician_name(client):
    ticket = post_ticket(client, urgency="emergency", duration=60, confidence=0.99).json()
    r = client.post("/alerts/oncall", json={"ticket_id": ticket["id"]})
    assert r.status_code == 201
    assert r.json()["technician_name"] == "Mike Smith"
    assert r.json()["ticket_id"] == ticket["id"]


def test_create_oncall_alert_nonexistent_ticket(client):
    r = client.post("/alerts/oncall", json={"ticket_id": "bad-id"})
    assert r.status_code == 404


# ── On-call location ───────────────────────────────────────────────────────────

def test_update_technician_location(client):
    r = client.patch("/oncall/location", json={"building_id": BLDG_2_ID})
    assert r.status_code == 200
    assert r.json()["current_building_id"] == BLDG_2_ID


def test_update_technician_location_invalid_building(client):
    r = client.patch("/oncall/location", json={"building_id": "not-a-real-building"})
    assert r.status_code == 404


# ── Schedule ───────────────────────────────────────────────────────────────────

def test_schedule_empty_initially(client):
    r = client.get("/schedule")
    assert r.status_code == 200
    data = r.json()
    assert data["paused"] is False
    assert data["items"] == []


def test_schedule_paused_when_emergency_open(client):
    post_ticket(client, urgency="emergency", duration=60, confidence=0.99)
    r = client.get("/schedule")
    assert r.json()["paused"] is True


def test_schedule_unpaused_after_emergency_completed(client):
    emrg = post_ticket(client, urgency="emergency", duration=60, confidence=0.99).json()
    post_ticket(client, urgency="urgent", duration=30, tenant_id=TENANT_2_ID, confidence=0.9)
    client.patch(f"/tickets/{emrg['id']}", json={"status": "completed"})
    r = client.get("/schedule")
    data = r.json()
    assert data["paused"] is False
    assert len(data["items"]) > 0


def test_schedule_has_travel_block_between_different_buildings(client):
    post_ticket(client, urgency="urgent", duration=30, tenant_id=TENANT_1_ID, confidence=0.9)
    post_ticket(client, urgency="urgent", duration=30, tenant_id=TENANT_2_ID, confidence=0.9)
    r = client.get("/schedule")
    types = [item["type"] for item in r.json()["items"]]
    assert "travel" in types


def test_schedule_no_travel_block_for_single_building(client):
    post_ticket(client, urgency="urgent", duration=30, tenant_id=TENANT_1_ID, confidence=0.9)
    r = client.get("/schedule")
    types = [item["type"] for item in r.json()["items"]]
    assert "travel" not in types


def test_incomplete_tickets_excluded_from_schedule(client):
    incomplete = post_ticket(client, status="incomplete", urgency="urgent", duration=30).json()
    r = client.get("/schedule")
    ticket_ids = [i["ticket"]["id"] for i in r.json()["items"] if i["type"] == "ticket"]
    assert incomplete["id"] not in ticket_ids


def test_schedule_items_ordered_by_start_time(client):
    post_ticket(client, urgency="urgent", duration=30, tenant_id=TENANT_1_ID, confidence=0.9)
    post_ticket(client, urgency="routine", duration=15, tenant_id=TENANT_2_ID, confidence=0.8)
    r = client.get("/schedule")
    starts = [item["start"] for item in r.json()["items"]]
    assert starts == sorted(starts)
