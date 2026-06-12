"""Unit tests for triage LLM call and summarization."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.triage import run_triage, summarize_issue, TriageResult


def _mock_openai(content: dict):
    response = MagicMock()
    response.choices[0].message.content = json.dumps(content)
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)
    return mock_client


# ── run_triage ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_triage_emergency():
    client = _mock_openai({
        "severity": "emergency",
        "confidence": 0.97,
        "reasoning": "Active flooding risk.",
        "suggested_instructions": "Turn off the water main.",
        "estimated_duration_minutes": 60,
    })
    with patch("agent.triage._get_client", return_value=client):
        result = await run_triage("Water pouring through ceiling", "Alice", "1A")
    assert result.severity == "emergency"
    assert result.confidence == 0.97
    assert result.suggested_instructions == "Turn off the water main."
    assert result.estimated_duration_minutes == 60


@pytest.mark.asyncio
async def test_run_triage_urgent():
    client = _mock_openai({
        "severity": "urgent",
        "confidence": 0.85,
        "reasoning": "No hot water is disruptive.",
        "suggested_instructions": None,
        "estimated_duration_minutes": 30,
    })
    with patch("agent.triage._get_client", return_value=client):
        result = await run_triage("No hot water since yesterday")
    assert result.severity == "urgent"
    assert result.suggested_instructions is None


@pytest.mark.asyncio
async def test_run_triage_routine():
    client = _mock_openai({
        "severity": "routine",
        "confidence": 0.9,
        "reasoning": "Dripping faucet is low stakes.",
        "suggested_instructions": None,
        "estimated_duration_minutes": 15,
    })
    with patch("agent.triage._get_client", return_value=client):
        result = await run_triage("Dripping faucet in kitchen")
    assert result.severity == "routine"


@pytest.mark.asyncio
async def test_run_triage_rounds_duration_to_nearest_five():
    client = _mock_openai({
        "severity": "routine", "confidence": 0.8, "reasoning": "x",
        "suggested_instructions": None, "estimated_duration_minutes": 17,
    })
    with patch("agent.triage._get_client", return_value=client):
        result = await run_triage("issue")
    assert result.estimated_duration_minutes == 15


@pytest.mark.asyncio
async def test_run_triage_enforces_minimum_duration_of_five():
    client = _mock_openai({
        "severity": "routine", "confidence": 0.8, "reasoning": "x",
        "suggested_instructions": None, "estimated_duration_minutes": 2,
    })
    with patch("agent.triage._get_client", return_value=client):
        result = await run_triage("issue")
    assert result.estimated_duration_minutes == 5


@pytest.mark.asyncio
async def test_run_triage_passes_tenant_context():
    client = _mock_openai({
        "severity": "routine", "confidence": 0.8, "reasoning": "x",
        "suggested_instructions": None, "estimated_duration_minutes": 15,
    })
    with patch("agent.triage._get_client", return_value=client):
        await run_triage("Broken hinge", tenant_name="Bob", unit="2B")
    call_args = client.chat.completions.create.call_args
    user_message = next(m for m in call_args[1]["messages"] if m["role"] == "user")
    assert "Bob" in user_message["content"]
    assert "2B" in user_message["content"]


# ── summarize_issue ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summarize_issue_returns_string():
    response = MagicMock()
    response.choices[0].message.content = "  Tenant reports water leaking from ceiling in bedroom.  "
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    with patch("agent.triage._get_client", return_value=client):
        summary = await summarize_issue("Water coming through bedroom ceiling", "emergency")
    assert isinstance(summary, str)
    assert summary == "Tenant reports water leaking from ceiling in bedroom."


@pytest.mark.asyncio
async def test_summarize_issue_passes_severity():
    response = MagicMock()
    response.choices[0].message.content = "summary"
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    with patch("agent.triage._get_client", return_value=client):
        await summarize_issue("Broken hinge on cabinet door", "routine")
    call_args = client.chat.completions.create.call_args
    user_message = next(m for m in call_args[1]["messages"] if m["role"] == "user")
    assert "routine" in user_message["content"]
