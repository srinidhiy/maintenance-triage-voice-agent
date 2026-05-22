# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Before starting any session

1. Read `.claude/TECH_SPEC.md` — it is the source of truth for all architectural decisions. Flag any deviation before implementing.
2. Check `.claude/ERRORS.md` before suggesting approaches to tasks that have failed before.
3. Check `MEMORY.md` in the project memory directory for session history and open decisions.

## Project overview

Voice-first maintenance triage system for Harborview Residential (8 buildings, ~600 units). Inbound calls via Twilio are handled by a Pipecat voice agent that identifies the tenant, gathers issue details, triages severity via an LLM, takes action (page on-call or create a ticket), and confirms the outcome. A React dashboard lets maintenance staff manage the queue, emergency board, and completed requests.

All external integrations are mocked — no live Twilio billing, no real on-call paging, no production database.

## Tech stack

| Layer | Technology |
|---|---|
| Telephony | Twilio (inbound PSTN, STT/TTS via Media Streams) |
| Voice agent | Pipecat + Pipecat Flows (conversation state machine) |
| Backend | FastAPI (REST API + Pipecat WebSocket endpoint on same server) |
| LLM | GPT-5.4 (triage), GPT-5.4-mini (call summarization) |
| Frontend | React (dashboard only, no voice UI) |
| Storage | Flat JSON files (`buildings.json`, `travel_times.json`, `tenants.json`, `tickets.json`, `oncall.json`, `alerts.json`) |
| Tunnel | Ngrok (exposes local FastAPI to Twilio webhook) |

## Architecture

```
Inbound call (Twilio)
        │
        ▼
  Voice Agent (Pipecat + FastAPI WebSocket)
        │  ← tool calls: tenant lookup, ticket write, on-call alert
        ▼
  Triage LLM (GPT-5.4)
        │  ← returns: severity, confidence, reasoning, instructions, estimated_duration_minutes
        ▼
  Voice Agent (communicates outcome to tenant, ends call)
        │
        ▼
  JSON data layer (loaded on startup, written back on every mutation)
        │
        ▼
  React Dashboard (polls GET /tickets and GET /schedule every 15s)
```

## Key design decisions

**Tenant identification:** Twilio caller ID pre-populates via `GET /tenants?phone=` before the conversation starts. Falls back to asking name/unit if no match.

**Triage confidence:** Agent asks up to 2 clarification rounds. If still ambiguous, defaults to the safer (higher) severity tier, tells the tenant, and stores `confidence` + `reasoning` on the ticket.

**Severity tiers:**
- `emergency` — active safety/health/property risk → page on-call immediately
- `urgent` — disruptive but not dangerous → priority ticket, same-day commitment
- `routine` — low stakes → standard ticket

**Mid-call disconnect:** Saves a draft ticket marked `status: incomplete`. No automatic callback.

**Scheduling algorithm (see TECH_SPEC.md §12 for full detail):**
- Emergencies never enter the schedule queue — Emergency Board only.
- While any emergency is `open` or `in_progress`, the schedule queue is paused (all `scheduled_start` → null).
- Non-emergency tickets are route-optimized within each tier using a nearest-neighbor TSP heuristic across up to 8 buildings.
- Urgents flagged `at_risk: true` if projected to exceed end of business day.
- Recompute runs on every mutation: new ticket, status change, last emergency completed, duration edit, technician location update.

**Storage:** JSON files are loaded into memory on startup and written back on every mutation. This is safe for single-call-at-a-time scope. Concurrency-safe storage (SQLite → Postgres) is a backlog item — do not implement it yet.

**No auth** in the initial build.

## Running the project (once implemented)

The project has not been scaffolded yet. Expected commands once set up:

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Tunnel (in separate terminal)
ngrok http 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Scope boundaries

Do not implement these — they are explicitly out of scope for the initial build:
- Concurrent call handling or session isolation
- Real on-call paging (PagerDuty, SMS)
- Dashboard or API authentication
- Multi-language support
- Postgres or SQLite migration
