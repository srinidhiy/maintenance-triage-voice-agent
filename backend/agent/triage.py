import json
import os
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel

TRIAGE_MODEL = os.getenv("TRIAGE_MODEL", "gpt-4o")

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client

_SYSTEM_PROMPT = """
You are a maintenance triage assistant for a residential property.
Given a tenant's issue description, classify the severity and estimate repair time.

Respond with a JSON object containing exactly these fields:
- severity: "emergency" | "urgent" | "routine"
  - emergency: active risk to safety, health, or major property damage
    (flooding, gas smell, no heat in winter, complete power loss, fire)
  - urgent: disruptive but not dangerous
    (no hot water, broken entry lock, HVAC failure in summer)
  - routine: inconvenient, low stakes
    (dripping faucet, broken hinge, burned-out bulb)
- confidence: float 0.0-1.0 (how confident you are in the classification)
- reasoning: one sentence explaining your classification
- suggested_instructions: safety instructions to read to the tenant RIGHT NOW
    (only for emergency severity; null otherwise)
- estimated_duration_minutes: integer, multiple of 5, minimum 5
    (your best estimate of repair time)

Return only valid JSON. No markdown, no explanation outside the JSON.
""".strip()


class TriageResult(BaseModel):
    severity: str
    confidence: float
    reasoning: str
    suggested_instructions: Optional[str]
    estimated_duration_minutes: int


async def run_triage(
    issue_description: str,
    tenant_name: Optional[str] = None,
    unit: Optional[str] = None,
) -> TriageResult:
    context = f"Issue: {issue_description}"
    if tenant_name:
        context = f"Tenant: {tenant_name}, Unit: {unit}\n{context}"

    response = await _get_client().chat.completions.create(
        model=TRIAGE_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        temperature=0.1,
    )

    data = json.loads(response.choices[0].message.content)

    # Enforce multiple-of-5 and minimum-5 on the duration
    raw_duration = int(data.get("estimated_duration_minutes", 15))
    duration = max(5, round(raw_duration / 5) * 5)

    return TriageResult(
        severity=data["severity"],
        confidence=float(data["confidence"]),
        reasoning=data["reasoning"],
        suggested_instructions=data.get("suggested_instructions"),
        estimated_duration_minutes=duration,
    )
