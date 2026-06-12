from datetime import datetime, timedelta, time
from collections import defaultdict
from typing import Optional

BUSINESS_START_HOUR = 8
BUSINESS_END_HOUR = 18


def _build_travel_lookup(travel_times: list) -> dict:
    lookup = {}
    for tt in travel_times:
        f, t, m = tt["from_building"], tt["to_building"], tt["minutes"]
        lookup[(f, t)] = m
        lookup[(t, f)] = m
    return lookup


def _next_business_window(now: datetime) -> datetime:
    today_open = now.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
    today_close = now.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)
    if now <= today_open:
        return today_open
    if now < today_close:
        return now
    tomorrow = now.date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(BUSINESS_START_HOUR, 0))


def _nearest_neighbor_route(buildings_with_tickets: dict, start: Optional[str], travel_lookup: dict) -> list:
    """Returns ordered list of building IDs using nearest-neighbor TSP heuristic."""
    if not buildings_with_tickets:
        return []

    unvisited = set(buildings_with_tickets.keys())

    if start and start in unvisited:
        current = start
    elif start:
        current = min(unvisited, key=lambda b: travel_lookup.get((start, b), 9999))
    else:
        current = next(iter(unvisited))

    route = []
    while unvisited:
        if current in unvisited:
            route.append(current)
            unvisited.remove(current)
        if unvisited:
            current = min(unvisited, key=lambda b: travel_lookup.get((current, b), 9999))

    return route


def compute_schedule(
    tickets: list,
    oncall: list,
    tenants_by_id: dict,
    travel_times: list,
    now: datetime,
) -> tuple[dict, list]:
    """
    Returns (updates, travel_blocks).

    updates: dict mapping ticket_id -> {scheduled_start (ISO str or None), at_risk (bool)}
    travel_blocks: list of travel gap dicts for the schedule view

    Does not mutate input lists.
    """
    travel_lookup = _build_travel_lookup(travel_times)

    schedulable = [
        t for t in tickets
        if t["urgency"] != "emergency" and t["status"] in ("open", "in_progress")
    ]
    active_emergencies = [
        t for t in tickets
        if t["urgency"] == "emergency" and t["status"] in ("open", "in_progress")
    ]

    updates = {t["id"]: {"scheduled_start": None, "at_risk": False} for t in schedulable}

    if active_emergencies:
        return updates, []

    def get_building(ticket: dict) -> Optional[str]:
        tenant = tenants_by_id.get(ticket.get("tenant_id"))
        return tenant["building_id"] if tenant else None

    urgents = sorted(
        [t for t in schedulable if t["urgency"] == "urgent"],
        key=lambda t: t["created_at"],
    )
    routines = sorted(
        [t for t in schedulable if t["urgency"] == "routine"],
        key=lambda t: t["created_at"],
    )

    tech = next((o for o in oncall if o.get("active")), None)
    tech_building = tech["current_building_id"] if tech else None

    def group_by_building(ticket_list: list) -> dict:
        grouped = defaultdict(list)
        for t in ticket_list:
            bldg = get_building(t)
            if bldg:
                grouped[bldg].append(t)
        for bldg in grouped:
            grouped[bldg].sort(key=lambda t: t["created_at"])
        return dict(grouped)

    urgent_by_building = group_by_building(urgents)
    urgent_start = tech_building
    if not urgent_start and urgents:
        urgent_start = get_building(min(urgents, key=lambda t: t["created_at"]))

    urgent_route = _nearest_neighbor_route(urgent_by_building, urgent_start, travel_lookup)
    last_urgent_building = urgent_route[-1] if urgent_route else tech_building

    routine_by_building = group_by_building(routines)
    routine_start = last_urgent_building
    if not routine_start and routines:
        routine_start = get_building(min(routines, key=lambda t: t["created_at"]))

    routine_route = _nearest_neighbor_route(routine_by_building, routine_start, travel_lookup)

    ordered = []
    for bldg in urgent_route:
        ordered.extend(urgent_by_building[bldg])
    for bldg in routine_route:
        ordered.extend(routine_by_building[bldg])

    schedule_start = _next_business_window(now)
    eob = schedule_start.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)
    current_time = schedule_start
    prev_building = tech_building
    travel_blocks = []

    for ticket in ordered:
        bldg = get_building(ticket)
        if prev_building and bldg and prev_building != bldg:
            travel_min = travel_lookup.get((prev_building, bldg), 0)
            travel_blocks.append({
                "from_building": prev_building,
                "to_building": bldg,
                "duration_minutes": travel_min,
                "start": current_time.isoformat(),
            })
            current_time += timedelta(minutes=travel_min)

        end_time = current_time + timedelta(minutes=ticket["estimated_duration_minutes"])
        at_risk = ticket["urgency"] == "urgent" and end_time > eob

        updates[ticket["id"]] = {
            "scheduled_start": current_time.isoformat(),
            "at_risk": at_risk,
        }

        current_time = end_time
        prev_building = bldg

    return updates, travel_blocks
