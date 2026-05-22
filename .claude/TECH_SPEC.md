# Harborview After-Hours Maintenance Agent — Technical Specification

## 1. Overview

A voice-first maintenance triage system for Harborview Residential (8 buildings, ~600 units). Inbound maintenance calls are handled by a voice agent that identifies the tenant, gathers issue details, classifies severity, takes appropriate action (page on-call or log a ticket), and communicates the outcome back to the tenant. A web dashboard lets maintenance staff monitor active issues, the schedule, and completed requests.

---

## 2. Goals

1. Eliminate the voicemail black hole — every call is assessed and routed in real time.
2. Reduce unnecessary on-call pages — only genuine emergencies trigger an alert.
3. Provide maintenance staff a dashboard to monitor and manage all requests.

---

## 3. System Architecture

```
Inbound call (Twilio)
        │
        ▼
  Voice Agent (Pipecat + FastAPI)
        │  ← tenant lookup, ticket write, on-call alert (tool calls)
        │
        ▼
  Triage Agent (LLM)
        │  ← classifies severity, returns structured result
        │
        ▼
  Voice Agent (continue call)
        │  ← communicates outcome to tenant, ends call
        │
        ▼
  Data Layer (local storage — JSON / SQLite)
        │
        ▼
  React Dashboard (reads via REST API)
```

All external integrations are mocked. No live databases, no real SMS/page, no real Twilio billing beyond the phone number.

---

## 4. Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Telephony | Twilio | Inbound PSTN calls, STT/TTS via Twilio Media Streams |
| Voice agent framework | Pipecat + Pipecat Flows | Structured conversation state machine |
| Backend | FastAPI | Serves REST API and Pipecat WebSocket endpoint |
| Triage LLM | GPT-5.4 (triage), GPT-5.4-mini (call summarization) | |
| Frontend | React | Dashboard only, no voice UI |
| Storage | Flat JSON files | Single-call-at-a-time scope; concurrency and Postgres are backlog items |
| Tunnel | Ngrok | Exposes local FastAPI to Twilio webhook |
| Logging | Python `logging` module | Structured logs for every tool call |

**Future / stretch:**
- Switch voice model to GPT Realtime API (for testing/comparison against Pipecat default)
- Host on VPS with Postgres

---

## 5. Conversation Flow

### 5.1 Phases

```
[1] Greeting
[2] Tenant Identification   → tool: GET /tenants/{unit or name}
[3] Issue Gathering         → follow-up questions until confident
[4] Triage                  → LLM classifies severity
[5] Action                  → tool calls based on classification
[6] Tenant Acknowledgment   → communicate outcome
[7] Graceful End
```

### 5.2 Phase Detail

**[1] Greeting**
Warm, calm opening. Acknowledge it may be off-hours. Do not sound robotic.

**[2] Tenant Identification**
Twilio passes the caller's phone number in the webhook payload. The agent uses this to pre-populate tenant identity by calling `GET /tenants?phone={caller_id}` before the conversation starts. If a match is found, the agent confirms the tenant's name ("Am I speaking with [Name] in unit [X]?") rather than asking them to identify themselves. If no phone match is found, fall back to asking for name or unit number. Unmatched tenants are flagged on the ticket.

**[3] Issue Gathering**
Ask open-ended: "Can you describe what's happening?" Follow up until the agent has enough detail to classify with confidence. Minimum required: location in unit, nature of issue, when it started. Use at most 2–3 follow-up questions before making a best-effort classification.

Tone guidance: context-aware based on time of day and stated urgency. A tenant describing flooding at 2am gets a calm, decisive tone. A daytime call about a dripping faucet gets a friendly, efficient tone.

**[4] Triage**
The voice agent hands the gathered context to the triage LLM with a structured prompt. The triage LLM returns:
- `severity`: `emergency | urgent | routine`
- `confidence`: `0.0–1.0`
- `reasoning`: brief explanation
- `suggested_instructions`: what to tell the tenant (for emergencies)
- `estimated_duration_minutes`: integer, multiple of 5, minimum 5 — the triage LLM's best estimate of how long the job will take (e.g. unclogging a drain → 5 min, replacing a door hinge → 20 min)

**[5] Action (by severity)**

| Severity | Actions |
|---|---|
| Emergency | `POST /tickets` (status: emergency), `POST /alerts/oncall`, voice agent reads instructions to tenant |
| Urgent | `POST /tickets` (status: urgent, priority: high), voice agent commits to same-day response |
| Routine | `POST /tickets` (status: routine), voice agent gives expected timeframe |

**[6] Tenant Acknowledgment**
Confirm what was done: "I've logged your ticket / I've paged the on-call technician." Give concrete next steps.

**[7] Graceful End**
Thank the tenant. Confirm they know what to expect. Offer emergency services number if situation is life-threatening and outside scope.

### 5.3 Ambiguity Handling
If the tenant's description is insufficient, the agent pushes back with targeted follow-up questions before escalating to triage. The agent should attempt up to 2 rounds of clarification (e.g. "Can you tell me a bit more — is there any water, smoke, or anything that feels urgent?"). Only after those attempts, if the description is still insufficient, does the agent hand off to the triage LLM. The triage LLM then defaults to the safer (higher) severity tier, returns a low confidence score, and the agent briefly acknowledges the ambiguity to the tenant: "I want to make sure this gets the right attention, so I'm treating this as [severity] just to be safe." The confidence score and reasoning are recorded on the ticket for staff visibility.

### 5.4 Mid-Call Disconnect
If Twilio signals that the call ended before the triage phase completed, the agent saves a draft ticket with whatever was captured (tenant identity if confirmed, partial issue description, timestamp) and marks it `status: incomplete`. This appears on the dashboard so staff can decide whether to follow up. No automatic callback attempt in the initial build.

---

## 6. Severity Classification

| Tier | Definition | Examples | Response |
|---|---|---|---|
| Emergency | Active risk to safety, health, or major property damage | Flooding, gas smell, no heat in winter, complete power loss | Page on-call immediately, give tenant instructions |
| Urgent | Disruptive, not dangerous | No hot water, broken entry lock, HVAC failure in summer | Priority ticket, same-day response commitment |
| Routine | Inconvenient, low stakes | Dripping faucet, broken hinge, burned-out bulb | Standard ticket, next available slot |

---

## 7. Data Layer

### 7.1 Seed Data (data.py or equivalent)

- 8 buildings with names
- Travel time matrix: constant mapping between every building pair (e.g. building 1 → building 2: 20 min)
- 10 mock tenants spread across the 8 buildings
- Empty ticket log (appended at runtime)
- On-call roster with one active technician

### 7.2 Schema

**Building**
```
id      UUID
name    string      (e.g. "Harbor North", "Harbor South")
```

**TravelTimes** (stored as a flat lookup, not a full entity)
```
Keyed by (building_id, building_id) → int (minutes)
Symmetric: travel_times[(A, B)] == travel_times[(B, A)]
Stored in travel_times.json as a list of {from, to, minutes}
```

**Tenant**
```
id              UUID
name            string
unit            string          (e.g. "4B")
building_id     UUID (FK → Building)
phone           string
```

**Ticket**
```
id                          UUID
tenant_id                   UUID (FK → Tenant)
urgency                     enum: emergency | urgent | routine
summary                     string          (GPT-5.4-mini cleaned summary of the call)
status                      enum: open | in_progress | completed | incomplete
confidence                  float (0.0–1.0)
instructions                string          (what was told to the tenant)
estimated_duration_minutes  int             (multiple of 5, minimum 5 — set by triage LLM, editable by technician)
scheduled_start             datetime | null (set by scheduling algorithm, null until placed)
raw_turns                   list[{role: "agent"|"tenant", text: string, timestamp: datetime}]
created_at                  datetime
updated_at                  datetime
```

**OnCallRoster**
```
id                   UUID
technician_name      string
phone                string
active               bool
current_building_id  UUID | null     (FK → Building; updated when technician starts a job; used as route optimization starting point)
```

**EmergencyAlert**
```
id              UUID
ticket_id       UUID (FK → Ticket)
technician_name string
alerted_at      datetime
```

### 7.3 Storage Implementation
Flat JSON files: `buildings.json`, `travel_times.json`, `tenants.json`, `tickets.json`, `oncall.json`, `alerts.json`. Loaded into memory on startup, written back on every mutation. This is safe for single-call-at-a-time scope. Concurrency-safe storage (SQLite → Postgres) is a backlog item.

---

## 8. API Endpoints

```
GET  /buildings                 List all buildings
GET  /tenants/{unit}            Look up tenant by unit number
GET  /tenants?name={name}       Look up tenant by name (fuzzy match)
GET  /tenants?phone={phone}     Look up tenant by phone (Twilio caller ID pre-population)
POST /tickets                   Create new ticket; triggers queue recompute
GET  /tickets                   List all tickets (filterable by status, urgency, building_id)
GET  /tickets/{id}              Get single ticket
GET  /tickets/emergency         Active emergency tickets only (dashboard use)
PATCH /tickets/{id}             Update ticket fields (status, estimated_duration_minutes); triggers queue recompute
POST /alerts/oncall             Log emergency alert, mock-page technician
PATCH /oncall/location          Update technician's current_building_id; triggers queue recompute
GET  /schedule                  Returns open non-emergency tickets with computed scheduled_start values and travel time blocks, ordered by queue position
```

All endpoints return JSON. No authentication for initial build.

---

## 9. Dashboard (React)

### 9.1 Pages

**Page 1 — Emergency Board**
- Real-time list of active emergency tickets in chronological order
- Each card: tenant name, unit, building, issue summary, time elapsed since alert, on-call technician notified, status (open / in_progress)
- Technician manually selects which emergency to handle first and marks it `in_progress` — no auto-routing for emergencies
- Marking the last emergency `completed` clears the board and unpauses the schedule queue
- Refreshes on a short polling interval (or WebSocket if feasible)

**Page 2 — Schedule (Calendar View)**
- Google Calendar-style layout showing open urgent + routine tickets
- Each event: tenant name, unit, building name, issue summary, severity badge, call summary, estimated duration
- Travel time gaps between buildings appear as distinct read-only blocks (e.g. "Travel: Harbor North → Harbor South — 20 min")
- While any emergency is open, the calendar shows all events with `scheduled_start: TBD` and a banner: "Schedule paused — emergency in progress"
- Urgent tickets flagged `at_risk` (projected to fall outside business hours) are visually highlighted
- When the queue recomputes, all scheduled_start values update and the calendar re-renders
- Clicking a ticket event shows full ticket detail + call summary

**Page 3 — Completed Requests**
- Read-only log of resolved tickets
- Filterable by date, severity, building

### 9.2 Data Fetching
React app polls `GET /tickets` and `GET /schedule`. No real-time WebSocket in initial build; polling interval TBD (suggest 15s).

---

## 10. Demo Scenarios

| Scenario | Trigger | Expected Path |
|---|---|---|
| Emergency | "Water is coming through my ceiling" | Identify → probe (how much, is it spreading) → emergency → page on-call → give instructions |
| Urgent | "No hot water since last night" | Identify → confirm duration → urgent → priority ticket → same-day commitment |
| Ambiguous → Routine | "Something's broken in my kitchen" | Identify → probe (what, where, does it affect safety) → cabinet hinge → routine → standard ticket |

---

## 11. Evaluation Harness (stretch goal)

A test runner that replays scripted call transcripts against the agent and asserts:
- Correct severity classification
- Correct tool calls made (which endpoints were hit)
- Transcript quality (subjective, human-reviewed)

Planned additional test scenarios beyond the core 3:
- Tenant not found in database
- Tenant describes vague issue, refuses to give more detail
- Mid-call disconnect (partial data)
- Multiple concurrent inbound calls
- Repeat caller (same issue called in twice)
- Non-emergency after hours (tenant explicitly asks if this is urgent)

---

## 12. Scheduling Algorithm

**Assumptions:** 8 buildings, one technician, constant travel times between buildings.

**Duration:** The triage LLM assigns `estimated_duration_minutes` (multiples of 5, min 5). Technicians can override this on any calendar event; the change triggers a full queue recompute.

**Core principle:** Within each tier, minimize total travel time across buildings so the technician can complete as many tickets as possible within the business day. This matters most for urgents — a suboptimal route wastes travel time and may push urgents past end of day.

**Emergency interaction with the schedule queue:**
- Emergency tickets never enter the schedule queue. They live exclusively on the Emergency Board.
- While any emergency is `open` or `in_progress`, the schedule queue is **paused**: all `scheduled_start` values are set to `null` and the dashboard shows a "schedule paused — emergency in progress" banner.
- The technician decides the order of multiple emergencies manually on the Emergency Board (they have on-the-ground context the system doesn't).
- If an emergency arrives while the technician is mid-job on an urgent, they finish the current job first (abandoning mid-job can worsen the situation), then move to the emergency. The Emergency Board surfaces the incoming alert immediately so the tech is aware.
- When the last open emergency is marked `completed`, `current_building_id` updates to the emergency's building and a full queue recompute runs from that building.

**Route optimization (per tier):**
- Group tickets by building within the tier.
- Find the minimum-travel route through all buildings that have tickets in that tier using a nearest-neighbor TSP heuristic. With at most 8 buildings this is fast and the heuristic is sufficient.
- Starting point for urgents: the technician's `current_building_id`, or the earliest-created urgent's building if `current_building_id` is null.
- Starting point for routines: the last building visited in the urgent tier, or earliest-created routine's building if no urgents.
- Within each building stop, schedule tickets FIFO by `created_at`.

**Scheduled start computation:**
- Queue starts from `max(now, next business window open)`.
- Walk the route-optimized order sequentially. For each ticket:
  - If the previous ticket was in a different building, insert a travel time gap: `travel_times[(prev_building, this_building)]`.
  - `scheduled_start = previous_end + travel_gap`.
  - `end = scheduled_start + estimated_duration_minutes`.
- After computing urgent scheduled_starts, flag any urgent ticket where `scheduled_start + estimated_duration_minutes > end_of_business_day` as `at_risk: true`. Surfaced on the dashboard so staff can intervene.
- `GET /schedule` returns the ordered ticket list interleaved with travel blocks `{from_building, to_building, duration_minutes, start}` for the calendar to render.

**Recompute triggers:**
- New ticket created (`POST /tickets`)
- Ticket status changes (`open` → `in_progress` → `completed`)
- Last open emergency marked `completed`
- Technician edits `estimated_duration_minutes`
- Technician location updated (`PATCH /oncall/location`)

All recomputes run a full route optimization from current state — no partial updates.

## 13. Backlog (deferred, not in scope for initial build)

- Concurrent call handling (multiple simultaneous Twilio sessions, session isolation)
- Concurrency-safe storage (SQLite → Postgres)
- Hosting on VPS
- Authentication on dashboard/API
- Real on-call paging integration
- Multi-language support

---

## 14. Out of Scope (initial build)

- Multi-language support
- Real Twilio billing / production phone numbers
- Real on-call paging (PagerDuty, SMS, etc.)
- Authentication / authorization on the dashboard or API
- Tenant mobile app or self-service portal
- SLA tracking or analytics
