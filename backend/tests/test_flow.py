"""Unit tests for flow handlers — tenant confirmation and issue submission."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.triage import TriageResult


def _make_flow_manager(state: dict = None):
    fm = MagicMock()
    fm.state = state or {}
    return fm


def _make_triage(severity="routine", confidence=0.9, instructions=None, duration=30):
    return TriageResult(
        severity=severity,
        confidence=confidence,
        reasoning="test reasoning",
        suggested_instructions=instructions,
        estimated_duration_minutes=duration,
    )


# ── _confirm_tenant ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_tenant_confirmed_leaves_state_unchanged():
    from agent.flow import _confirm_tenant
    fm = _make_flow_manager({"tenant": {"id": "t1", "name": "Alice", "unit": "1A"}})
    _, next_node = await _confirm_tenant({"confirmed": True}, fm)
    assert fm.state["tenant"]["name"] == "Alice"
    assert "unmatched" not in fm.state
    assert next_node["name"] == "gather_issue"


@pytest.mark.asyncio
async def test_confirm_tenant_not_confirmed_overwrites_tenant():
    from agent.flow import _confirm_tenant
    fm = _make_flow_manager({"tenant": {"id": "t1", "name": "Alice", "unit": "1A"}})
    _, next_node = await _confirm_tenant(
        {"confirmed": False, "name": "Bob Smith", "unit": "3C"}, fm
    )
    assert fm.state["tenant"]["name"] == "Bob Smith"
    assert fm.state["tenant"]["unit"] == "3C"
    assert fm.state["tenant"]["id"] is None
    assert fm.state["unmatched"] is True
    assert next_node["name"] == "gather_issue"


@pytest.mark.asyncio
async def test_confirm_tenant_unmatched_caller_sets_unmatched_flag():
    from agent.flow import _confirm_tenant
    fm = _make_flow_manager({})
    await _confirm_tenant({"confirmed": False, "name": "Unknown", "unit": "9Z"}, fm)
    assert fm.state.get("unmatched") is True


# ── _submit_issue ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_issue_creates_ticket():
    from agent.flow import _submit_issue
    fm = _make_flow_manager({"tenant": {"id": "t1", "name": "Alice", "unit": "1A"}})
    triage = _make_triage(severity="routine")

    with patch("agent.flow.run_triage", return_value=triage), \
         patch("agent.flow.summarize_issue", return_value="Dripping faucet in kitchen."), \
         patch("agent.flow._post", new_callable=AsyncMock) as mock_post:

        mock_post.return_value = {"id": "ticket-123"}
        _, next_node = await _submit_issue({"description": "Dripping faucet"}, fm)

    mock_post.assert_called_once_with("/tickets", {
        "tenant_id": "t1",
        "urgency": "routine",
        "summary": "Dripping faucet in kitchen.",
        "confidence": 0.9,
        "instructions": None,
        "estimated_duration_minutes": 30,
    })
    assert fm.state["ticket_id"] == "ticket-123"
    assert next_node["name"] == "acknowledge"


@pytest.mark.asyncio
async def test_submit_issue_emergency_pages_oncall():
    from agent.flow import _submit_issue
    fm = _make_flow_manager({"tenant": {"id": "t1", "name": "Alice", "unit": "1A"}})
    triage = _make_triage(severity="emergency", instructions="Turn off water main.", duration=60)

    with patch("agent.flow.run_triage", return_value=triage), \
         patch("agent.flow.summarize_issue", return_value="Flooding."), \
         patch("agent.flow._post", new_callable=AsyncMock) as mock_post:

        mock_post.return_value = {"id": "ticket-456"}
        await _submit_issue({"description": "Water flooding the unit"}, fm)

    assert mock_post.call_count == 2
    alert_call = mock_post.call_args_list[1]
    assert alert_call[0] == ("/alerts/oncall", {"ticket_id": "ticket-456"})


@pytest.mark.asyncio
async def test_submit_issue_non_emergency_does_not_page_oncall():
    from agent.flow import _submit_issue
    fm = _make_flow_manager({"tenant": {"id": "t1", "name": "Alice", "unit": "1A"}})

    for severity in ("urgent", "routine"):
        triage = _make_triage(severity=severity)
        with patch("agent.flow.run_triage", return_value=triage), \
             patch("agent.flow.summarize_issue", return_value="summary"), \
             patch("agent.flow._post", new_callable=AsyncMock) as mock_post:

            mock_post.return_value = {"id": "ticket-789"}
            await _submit_issue({"description": "some issue"}, fm)

        assert mock_post.call_count == 1, f"alert should not be called for {severity}"


@pytest.mark.asyncio
async def test_submit_issue_stores_triage_result_in_state():
    from agent.flow import _submit_issue
    fm = _make_flow_manager({"tenant": {"id": "t1", "name": "Alice", "unit": "1A"}})
    triage = _make_triage(severity="urgent")

    with patch("agent.flow.run_triage", return_value=triage), \
         patch("agent.flow.summarize_issue", return_value="summary"), \
         patch("agent.flow._post", new_callable=AsyncMock) as mock_post:

        mock_post.return_value = {"id": "ticket-001"}
        await _submit_issue({"description": "No hot water"}, fm)

    assert fm.state["triage"] is triage


@pytest.mark.asyncio
async def test_submit_issue_null_tenant_id_when_unmatched():
    from agent.flow import _submit_issue
    fm = _make_flow_manager({"tenant": {"id": None, "name": "Unknown", "unit": "9Z"}})
    triage = _make_triage()

    with patch("agent.flow.run_triage", return_value=triage), \
         patch("agent.flow.summarize_issue", return_value="summary"), \
         patch("agent.flow._post", new_callable=AsyncMock) as mock_post:

        mock_post.return_value = {"id": "ticket-002"}
        await _submit_issue({"description": "issue"}, fm)

    ticket_payload = mock_post.call_args_list[0][0][1]
    assert ticket_payload["tenant_id"] is None
