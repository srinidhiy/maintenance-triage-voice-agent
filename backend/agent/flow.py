"""Pipecat Flows conversation for the Harborview maintenance triage agent."""
import os
from typing import Optional

import httpx
from pipecat_flows import (
    ContextStrategy,
    ContextStrategyConfig,
    FlowArgs,
    FlowManager,
    FlowsFunctionSchema,
    NodeConfig,
)

from .triage import TriageResult, run_triage, summarize_issue

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

_ROLE = (
    "You are a calm, professional after-hours maintenance assistant for Harborview Residential. "
    "Keep responses brief — this is a phone call. "
    "Do not use lists, bullet points, or special characters."
)


# ── Internal API helpers ───────────────────────────────────────────────────────

async def _post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}{path}", json=body)
        r.raise_for_status()
        return r.json()


# ── Handlers ───────────────────────────────────────────────────────────────────

async def _confirm_tenant(args: FlowArgs, flow_manager: FlowManager):
    if not args.get("confirmed", False):
        flow_manager.state["tenant"] = {
            "id": None,
            "name": args.get("name"),
            "unit": args.get("unit"),
        }
        flow_manager.state["unmatched"] = True
    return {"ok": True}, _gather_node()


async def _submit_issue(args: FlowArgs, flow_manager: FlowManager):
    description = args["description"]
    tenant = flow_manager.state.get("tenant") or {}

    triage: TriageResult = await run_triage(
        description,
        tenant_name=tenant.get("name"),
        unit=tenant.get("unit"),
    )
    summary = await summarize_issue(description, triage.severity)

    ticket = await _post("/tickets", {
        "tenant_id": tenant.get("id"),
        "urgency": triage.severity,
        "summary": summary,
        "confidence": triage.confidence,
        "instructions": triage.suggested_instructions,
        "estimated_duration_minutes": triage.estimated_duration_minutes,
    })

    flow_manager.state["ticket_id"] = ticket["id"]
    flow_manager.state["triage"] = triage

    if triage.severity == "emergency":
        await _post("/alerts/oncall", {"ticket_id": ticket["id"]})

    return {"severity": triage.severity}, _acknowledge_node(triage)


async def _end_call(args: FlowArgs, flow_manager: FlowManager):
    return {"ok": True}, _end_node()


# ── Node definitions ───────────────────────────────────────────────────────────

def create_identify_node(tenant: Optional[dict]) -> NodeConfig:
    """Entry point node. `tenant` is pre-populated from Twilio caller ID lookup, or None."""
    if tenant:
        task = (
            f"Greet the caller warmly and acknowledge it may be off-hours. "
            f"You have a match on file: {tenant['name']}, unit {tenant['unit']}. "
            f"Confirm by asking: 'Am I speaking with {tenant['name']} in unit {tenant['unit']}?' "
            "If they confirm, call confirm_tenant with confirmed=true. "
            "If they say no, ask for their name and unit number, then call confirm_tenant "
            "with confirmed=false and the details they give you."
        )
    else:
        task = (
            "Greet the caller warmly and acknowledge it may be off-hours. "
            "You don't have their number on file. "
            "Ask for their name and unit number, then call confirm_tenant "
            "with confirmed=false and the details they provide."
        )

    return NodeConfig(
        name="identify",
        role_message=_ROLE,
        task_messages=[{"role": "developer", "content": task}],
        functions=[
            FlowsFunctionSchema(
                name="confirm_tenant",
                handler=_confirm_tenant,
                description="Record tenant identity and move to issue gathering.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "True if the pre-identified tenant confirmed who they are.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Tenant name, if not pre-identified or not confirmed.",
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unit number, if not pre-identified or not confirmed.",
                    },
                },
                required=["confirmed"],
            )
        ],
    )


def _gather_node() -> NodeConfig:
    return NodeConfig(
        name="gather_issue",
        role_message=_ROLE,
        task_messages=[{
            "role": "developer",
            "content": (
                "Ask the tenant to describe what's happening. "
                "You need: where in the unit, what the issue is, and when it started. "
                "Ask at most 2 follow-up questions if the description is vague. "
                "After at most 2 clarifications, call submit_issue with everything you have — "
                "do not keep asking. If still ambiguous, describe it as best you can."
            ),
        }],
        context_strategy=ContextStrategyConfig(strategy=ContextStrategy.RESET),
        functions=[
            FlowsFunctionSchema(
                name="submit_issue",
                handler=_submit_issue,
                description="Submit the issue for triage once you have enough detail.",
                properties={
                    "description": {
                        "type": "string",
                        "description": (
                            "Full description of the issue: what it is, where in the unit, "
                            "when it started, and any safety concerns."
                        ),
                    },
                },
                required=["description"],
            )
        ],
    )


def _acknowledge_node(triage: TriageResult) -> NodeConfig:
    if triage.severity == "emergency":
        task = (
            "Tell the tenant this is being treated as an emergency and the on-call technician "
            "has been paged. Read them these safety instructions: "
            f"'{triage.suggested_instructions}' "
            "Ask if they have any immediate questions, then call end_call."
        )
    elif triage.severity == "urgent":
        task = (
            "Tell the tenant their request has been logged as high priority "
            "and they can expect a same-day response. "
            "Ask if they have any questions, then call end_call."
        )
    else:
        task = (
            "Tell the tenant their request has been logged and maintenance "
            "will be in touch within 1-2 business days. "
            "Ask if they have any questions, then call end_call."
        )

    return NodeConfig(
        name="acknowledge",
        role_message=_ROLE,
        task_messages=[{"role": "developer", "content": task}],
        context_strategy=ContextStrategyConfig(strategy=ContextStrategy.RESET),
        functions=[
            FlowsFunctionSchema(
                name="end_call",
                handler=_end_call,
                description="End the call after the tenant has no further questions.",
                properties={},
                required=[],
            )
        ],
    )


def _end_node() -> NodeConfig:
    return NodeConfig(
        name="end",
        role_message=_ROLE,
        task_messages=[{
            "role": "developer",
            "content": "Thank the tenant, wish them well, and say goodbye.",
        }],
        post_actions=[{"type": "end_conversation"}],
    )
