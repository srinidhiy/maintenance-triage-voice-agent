from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from datetime import datetime
import uuid

import storage
import scheduling as sched
from models import (
    CreateTicketRequest,
    UpdateTicketRequest,
    CreateAlertRequest,
    UpdateLocationRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.load_all()
    _recompute_schedule()
    yield


app = FastAPI(title="Harborview Maintenance API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Buildings ---

@app.get("/buildings")
def list_buildings():
    return storage.get("buildings")


# --- Tenants ---

@app.get("/tenants")
def get_tenants(
    name: Optional[str] = Query(default=None),
    phone: Optional[str] = Query(default=None),
):
    tenants = storage.get("tenants")
    if phone:
        match = next((t for t in tenants if t["phone"] == phone), None)
        if not match:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return match
    if name:
        return [t for t in tenants if name.lower() in t["name"].lower()]
    return tenants


@app.get("/tenants/{unit}")
def get_tenant_by_unit(unit: str):
    tenants = storage.get("tenants")
    match = next((t for t in tenants if t["unit"].lower() == unit.lower()), None)
    if not match:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return match


# --- Tickets ---
# NOTE: /tickets/emergency must be defined before /tickets/{id} to prevent
# FastAPI routing "emergency" as a path parameter.

@app.get("/tickets/emergency")
def get_emergency_tickets():
    tickets = storage.get("tickets")
    return [
        t for t in tickets
        if t["urgency"] == "emergency" and t["status"] in ("open", "in_progress")
    ]


@app.get("/tickets")
def list_tickets(
    status: Optional[str] = Query(default=None),
    urgency: Optional[str] = Query(default=None),
    building_id: Optional[str] = Query(default=None),
):
    tickets = storage.get("tickets")
    result = tickets

    if status:
        result = [t for t in result if t["status"] == status]
    if urgency:
        result = [t for t in result if t["urgency"] == urgency]
    if building_id:
        tenants_by_id = {t["id"]: t for t in storage.get("tenants")}
        result = [
            t for t in result
            if tenants_by_id.get(t.get("tenant_id"), {}).get("building_id") == building_id
        ]

    return result


@app.post("/tickets", status_code=201)
def create_ticket(req: CreateTicketRequest):
    tickets = storage.get("tickets")
    now = datetime.utcnow()
    ticket = {
        "id": str(uuid.uuid4()),
        "tenant_id": req.tenant_id,
        "urgency": req.urgency,
        "summary": req.summary,
        "status": req.status,
        "confidence": req.confidence,
        "instructions": req.instructions,
        "estimated_duration_minutes": req.estimated_duration_minutes,
        "scheduled_start": None,
        "at_risk": False,
        "raw_turns": req.raw_turns or [],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    tickets.append(ticket)
    storage.save("tickets")
    _recompute_schedule()
    return ticket


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    match = next((t for t in storage.get("tickets") if t["id"] == ticket_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return match


@app.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: str, req: UpdateTicketRequest):
    match = next((t for t in storage.get("tickets") if t["id"] == ticket_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if req.status is not None:
        match["status"] = req.status
    if req.estimated_duration_minutes is not None:
        match["estimated_duration_minutes"] = req.estimated_duration_minutes
    match["updated_at"] = datetime.utcnow().isoformat()

    storage.save("tickets")
    _recompute_schedule()
    return match


# --- Alerts ---

@app.post("/alerts/oncall", status_code=201)
def create_oncall_alert(req: CreateAlertRequest):
    oncall = storage.get("oncall")
    tech = next((o for o in oncall if o.get("active")), None)
    if not tech:
        raise HTTPException(status_code=503, detail="No active technician on call")

    # Verify ticket exists
    ticket = next((t for t in storage.get("tickets") if t["id"] == req.ticket_id), None)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    alert = {
        "id": str(uuid.uuid4()),
        "ticket_id": req.ticket_id,
        "technician_name": tech["technician_name"],
        "alerted_at": datetime.utcnow().isoformat(),
    }
    storage.get("alerts").append(alert)
    storage.save("alerts")
    # Mock page — in production this would trigger PagerDuty / SMS
    return alert


# --- On-call location ---

@app.patch("/oncall/location")
def update_location(req: UpdateLocationRequest):
    buildings = storage.get("buildings")
    if not any(b["id"] == req.building_id for b in buildings):
        raise HTTPException(status_code=404, detail="Building not found")

    tech = next((o for o in storage.get("oncall") if o.get("active")), None)
    if not tech:
        raise HTTPException(status_code=503, detail="No active technician on call")

    tech["current_building_id"] = req.building_id
    storage.save("oncall")
    _recompute_schedule()
    return tech


# --- Schedule ---

@app.get("/schedule")
def get_schedule():
    tickets = storage.get("tickets")
    active_emergencies = [
        t for t in tickets
        if t["urgency"] == "emergency" and t["status"] in ("open", "in_progress")
    ]

    if active_emergencies:
        return {"paused": True, "reason": "Emergency in progress", "items": []}

    buildings_by_id = {b["id"]: b for b in storage.get("buildings")}
    tenants_by_id = {t["id"]: t for t in storage.get("tenants")}

    schedulable = [
        t for t in tickets
        if t["urgency"] != "emergency" and t["status"] in ("open", "in_progress")
        and t.get("scheduled_start")
    ]

    ticket_items = []
    for ticket in sorted(schedulable, key=lambda t: t["scheduled_start"]):
        tenant = tenants_by_id.get(ticket.get("tenant_id"), {})
        building = buildings_by_id.get(tenant.get("building_id"), {})
        ticket_items.append({
            "type": "ticket",
            "start": ticket["scheduled_start"],
            "ticket": ticket,
            "tenant_name": tenant.get("name"),
            "building_id": tenant.get("building_id"),
            "building_name": building.get("name"),
        })

    travel_items = []
    for tb in storage.get_travel_blocks():
        travel_items.append({
            "type": "travel",
            "start": tb["start"],
            "from_building": tb["from_building"],
            "to_building": tb["to_building"],
            "from_name": buildings_by_id.get(tb["from_building"], {}).get("name"),
            "to_name": buildings_by_id.get(tb["to_building"], {}).get("name"),
            "duration_minutes": tb["duration_minutes"],
        })

    items = sorted(ticket_items + travel_items, key=lambda x: x["start"])
    return {"paused": False, "items": items}


# --- Internal ---

def _recompute_schedule() -> None:
    tickets = storage.get("tickets")
    oncall = storage.get("oncall")
    tenants_by_id = {t["id"]: t for t in storage.get("tenants")}
    travel_times = storage.get("travel_times")

    updates, travel_blocks = sched.compute_schedule(
        tickets, oncall, tenants_by_id, travel_times, datetime.utcnow()
    )

    for ticket in tickets:
        if ticket["id"] in updates:
            ticket.update(updates[ticket["id"]])

    storage.save("tickets")
    storage.set_travel_blocks(travel_blocks)
