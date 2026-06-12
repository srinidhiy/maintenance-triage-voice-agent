"""Pipecat pipeline + Twilio transport for the Harborview maintenance agent."""
import os
from datetime import datetime
from typing import Optional

import aiohttp
import httpx
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner
from pipecat_flows import FlowManager
from starlette.websockets import WebSocket

from .flow import create_identify_node

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
AGENT_MODEL = os.getenv("AGENT_MODEL", "gpt-4o")


async def _get_caller_phone(call_sid: str) -> Optional[str]:
    """Fetch caller's phone number from Twilio REST API."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        return None
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{call_sid}.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=aiohttp.BasicAuth(account_sid, auth_token)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("from")
    except Exception as e:
        logger.warning(f"Could not fetch caller phone: {e}")
    return None


async def _lookup_tenant(phone: str) -> Optional[dict]:
    """Look up tenant by phone number via our REST API."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{API_BASE}/tenants", params={"phone": phone})
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f"Tenant lookup failed: {e}")
    return None


async def _save_incomplete_ticket(flow_manager: FlowManager) -> None:
    """Called on disconnect before triage completes. Saves a draft ticket."""
    if flow_manager.state.get("ticket_id"):
        return  # Ticket already created — nothing to do.

    tenant = flow_manager.state.get("tenant") or {}
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{API_BASE}/tickets", json={
                "tenant_id": tenant.get("id"),
                "urgency": "routine",
                "summary": "Call disconnected before issue was fully described.",
                "status": "incomplete",
                "confidence": 0.0,
                "estimated_duration_minutes": 5,
            })
    except Exception as e:
        logger.error(f"Failed to save incomplete ticket: {e}")


async def run_bot(websocket: WebSocket) -> None:
    """Set up and run the Pipecat pipeline for one inbound call."""
    _, call_data = await parse_telephony_websocket(websocket)
    call_sid = call_data["call_id"]
    stream_sid = call_data["stream_id"]

    # Pre-populate tenant from caller ID
    caller_phone = await _get_caller_phone(call_sid)
    tenant = await _lookup_tenant(caller_phone) if caller_phone else None
    if tenant:
        logger.info(f"Matched tenant: {tenant['name']} ({tenant['unit']})")
    else:
        logger.info("No tenant match — will ask caller to identify")

    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        model=AGENT_MODEL,
    )
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY", ""))
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY", ""),
        settings=CartesiaTTSService.Settings(
            voice=os.getenv("CARTESIA_VOICE_ID", "71a7ad14-091c-4e8e-a314-022ece01c121"),
        ),
    )

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            filter_incomplete_user_turns=True,
        ),
    )

    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ])

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
        ),
    )

    flow_manager = FlowManager(
        worker=worker,
        llm=llm,
        context_aggregator=context_aggregator,
        transport=transport,
    )
    flow_manager.state["tenant"] = tenant
    flow_manager.state["caller_phone"] = caller_phone

    @transport.event_handler("on_client_connected")
    async def on_connected(transport, client):
        logger.info(f"Call connected: {call_sid}")
        await flow_manager.initialize(create_identify_node(tenant))

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(transport, client):
        logger.info(f"Call disconnected: {call_sid}")
        await _save_incomplete_ticket(flow_manager)
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()
