"""Unit tests for the scheduling algorithm. No API or storage involvement."""
from datetime import datetime, timedelta

import scheduling

BLDG_1 = "11111111-0000-0000-0000-000000000001"  # Harbor North
BLDG_2 = "11111111-0000-0000-0000-000000000002"  # Harbor South
BLDG_3 = "11111111-0000-0000-0000-000000000003"  # Harbor East

TRAVEL_TIMES = [
    {"from_building": BLDG_1, "to_building": BLDG_2, "minutes": 10},
    {"from_building": BLDG_1, "to_building": BLDG_3, "minutes": 15},
    {"from_building": BLDG_2, "to_building": BLDG_3, "minutes": 20},
]

ONCALL_NO_LOCATION = [{"active": True, "current_building_id": None}]
DURING_BUSINESS = datetime(2026, 6, 11, 9, 0, 0)   # 9am
AFTER_BUSINESS = datetime(2026, 6, 11, 20, 0, 0)    # 8pm


def ticket(id, tenant_id, urgency, duration=30, status="open", created="2026-06-11T07:00:00"):
    return {
        "id": id,
        "tenant_id": tenant_id,
        "urgency": urgency,
        "status": status,
        "estimated_duration_minutes": duration,
        "created_at": created,
    }


def tenant(id, building_id):
    return {"id": id, "building_id": building_id}


# --- Basic behavior ---

def test_empty_tickets_returns_empty():
    updates, blocks = scheduling.compute_schedule([], ONCALL_NO_LOCATION, {}, TRAVEL_TIMES, DURING_BUSINESS)
    assert updates == {}
    assert blocks == []


def test_single_urgent_scheduled_at_now():
    tenants = {"t1": tenant("t1", BLDG_1)}
    updates, blocks = scheduling.compute_schedule(
        [ticket("u1", "t1", "urgent")], ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert updates["u1"]["scheduled_start"] == DURING_BUSINESS.isoformat()
    assert updates["u1"]["at_risk"] is False
    assert blocks == []


def test_completed_ticket_excluded_from_schedule():
    tenants = {"t1": tenant("t1", BLDG_1)}
    updates, _ = scheduling.compute_schedule(
        [ticket("u1", "t1", "urgent", status="completed")], ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert "u1" not in updates


def test_incomplete_ticket_excluded_from_schedule():
    tenants = {"t1": tenant("t1", BLDG_1)}
    updates, _ = scheduling.compute_schedule(
        [ticket("u1", "t1", "urgent", status="incomplete")], ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert "u1" not in updates


def test_emergency_ticket_excluded_from_schedule():
    tenants = {"t1": tenant("t1", BLDG_1)}
    updates, _ = scheduling.compute_schedule(
        [ticket("e1", "t1", "emergency")], ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert "e1" not in updates


# --- Emergency pause ---

def test_active_emergency_sets_all_scheduled_starts_to_null():
    tenants = {"t1": tenant("t1", BLDG_1), "t2": tenant("t2", BLDG_2)}
    tickets = [
        ticket("e1", "t1", "emergency"),
        ticket("u1", "t2", "urgent"),
        ticket("r1", "t2", "routine"),
    ]
    updates, blocks = scheduling.compute_schedule(
        tickets, ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert updates["u1"]["scheduled_start"] is None
    assert updates["r1"]["scheduled_start"] is None
    assert blocks == []


def test_in_progress_emergency_also_pauses_queue():
    tenants = {"t1": tenant("t1", BLDG_1), "t2": tenant("t2", BLDG_2)}
    tickets = [
        ticket("e1", "t1", "emergency", status="in_progress"),
        ticket("u1", "t2", "urgent"),
    ]
    updates, blocks = scheduling.compute_schedule(
        tickets, ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert updates["u1"]["scheduled_start"] is None
    assert blocks == []


# --- Travel blocks ---

def test_travel_block_inserted_between_buildings():
    tenants = {"t1": tenant("t1", BLDG_1), "t2": tenant("t2", BLDG_2)}
    t1 = ticket("t1", "t1", "urgent", duration=30, created="2026-06-11T07:00:00")
    t2 = ticket("t2", "t2", "urgent", duration=20, created="2026-06-11T07:05:00")
    updates, blocks = scheduling.compute_schedule(
        [t1, t2], ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert len(blocks) == 1
    assert blocks[0]["from_building"] == BLDG_1
    assert blocks[0]["to_building"] == BLDG_2
    assert blocks[0]["duration_minutes"] == 10
    expected_t2_start = DURING_BUSINESS + timedelta(minutes=30 + 10)
    assert updates["t2"]["scheduled_start"] == expected_t2_start.isoformat()


def test_no_travel_block_when_same_building():
    tenants = {"t1": tenant("t1", BLDG_1), "t2": tenant("t2", BLDG_1)}
    t1 = ticket("t1", "t1", "urgent", duration=30, created="2026-06-11T07:00:00")
    t2 = ticket("t2", "t2", "urgent", duration=20, created="2026-06-11T07:05:00")
    _, blocks = scheduling.compute_schedule(
        [t1, t2], ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert blocks == []


# --- Urgents before routines ---

def test_urgents_scheduled_before_routines():
    tenants = {"t1": tenant("t1", BLDG_1)}
    urgent = ticket("u1", "t1", "urgent", duration=30)
    routine = ticket("r1", "t1", "routine", duration=20)
    updates, _ = scheduling.compute_schedule(
        [routine, urgent], ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert updates["u1"]["scheduled_start"] < updates["r1"]["scheduled_start"]


def test_routines_start_after_last_urgent_ends():
    # Two urgents in different buildings, one routine. Routine must not start
    # until the second urgent finishes (including the travel gap between buildings).
    tenants = {
        "t1": tenant("t1", BLDG_1),
        "t2": tenant("t2", BLDG_2),
        "t3": tenant("t3", BLDG_2),
    }
    u1 = ticket("u1", "t1", "urgent", duration=30, created="2026-06-11T07:00:00")
    u2 = ticket("u2", "t2", "urgent", duration=20, created="2026-06-11T07:05:00")
    r1 = ticket("r1", "t3", "routine", duration=15, created="2026-06-11T07:10:00")
    updates, _ = scheduling.compute_schedule(
        [u1, u2, r1], ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    # u1 (BLDG_1) → travel 10 min → u2 (BLDG_2) → r1 (BLDG_2, no travel)
    u1_end = datetime.fromisoformat(updates["u1"]["scheduled_start"]) + timedelta(minutes=30)
    u2_start = u1_end + timedelta(minutes=10)   # travel BLDG_1 → BLDG_2
    u2_end = u2_start + timedelta(minutes=20)
    assert datetime.fromisoformat(updates["u2"]["scheduled_start"]) == u2_start
    assert datetime.fromisoformat(updates["r1"]["scheduled_start"]) == u2_end


# --- at_risk ---

def test_at_risk_true_when_urgent_ends_after_eob():
    tenants = {"t1": tenant("t1", BLDG_1)}
    # 9am start + 600 min = 7pm, past 6pm EOB
    updates, _ = scheduling.compute_schedule(
        [ticket("u1", "t1", "urgent", duration=600)],
        ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS,
    )
    assert updates["u1"]["at_risk"] is True


def test_at_risk_false_when_urgent_ends_before_eob():
    tenants = {"t1": tenant("t1", BLDG_1)}
    # 9am + 30 min = 9:30am, well before 6pm
    updates, _ = scheduling.compute_schedule(
        [ticket("u1", "t1", "urgent", duration=30)],
        ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS,
    )
    assert updates["u1"]["at_risk"] is False


def test_routine_never_flagged_at_risk_regardless_of_duration():
    tenants = {"t1": tenant("t1", BLDG_1)}
    updates, _ = scheduling.compute_schedule(
        [ticket("r1", "t1", "routine", duration=600)],
        ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, DURING_BUSINESS,
    )
    assert updates["r1"]["at_risk"] is False


# --- Business hours ---

def test_schedule_starts_next_day_when_called_after_hours():
    tenants = {"t1": tenant("t1", BLDG_1)}
    updates, _ = scheduling.compute_schedule(
        [ticket("u1", "t1", "urgent")],
        ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, AFTER_BUSINESS,
    )
    assert updates["u1"]["scheduled_start"] == "2026-06-12T08:00:00"


def test_at_risk_compares_against_eob_of_scheduled_day_not_today():
    # After hours call: schedule starts next day at 8am.
    # 30-min job ending 8:30am is NOT at_risk (EOB is next day's 6pm).
    tenants = {"t1": tenant("t1", BLDG_1)}
    updates, _ = scheduling.compute_schedule(
        [ticket("u1", "t1", "urgent", duration=30)],
        ONCALL_NO_LOCATION, tenants, TRAVEL_TIMES, AFTER_BUSINESS,
    )
    assert updates["u1"]["at_risk"] is False


# --- Technician starting location affects route ---

def test_tech_current_building_affects_route_start():
    oncall_at_bldg2 = [{"active": True, "current_building_id": BLDG_2}]
    tenants = {"t1": tenant("t1", BLDG_1), "t2": tenant("t2", BLDG_2)}
    # Tech is at BLDG_2, so t2 (BLDG_2) should be visited first (no travel)
    t1 = ticket("t1", "t1", "urgent", duration=30, created="2026-06-11T07:00:00")
    t2 = ticket("t2", "t2", "urgent", duration=20, created="2026-06-11T07:00:00")
    updates, blocks = scheduling.compute_schedule(
        [t1, t2], oncall_at_bldg2, tenants, TRAVEL_TIMES, DURING_BUSINESS
    )
    assert updates["t2"]["scheduled_start"] == DURING_BUSINESS.isoformat()
    expected_t1_start = DURING_BUSINESS + timedelta(minutes=20 + 10)
    assert updates["t1"]["scheduled_start"] == expected_t1_start.isoformat()
