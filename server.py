"""
Sam's Instagram DM Bot — Webhook Server
Receives ManyChat webhook → Calls Claude API → Sends response back via ManyChat sendFlow

SEND METHOD: setCustomFieldByName("bot_reply") + sendFlow(flow_ns)
This is the only method that works for IG-only subscribers in ManyChat.
/fb/sending/sendContent fails for IG subscribers (checks FB last_interaction, not IG).
/ig/sending/sendContent does not exist (404).
sendFlow bypasses the 24h window check entirely.

FLOW SETUP REQUIRED IN MANYCHAT:
1. Create a new Flow in ManyChat
2. Add a "Send Message" step with text: {{bot_reply}}
3. Publish the flow
4. Copy the flow_ns and set MANYCHAT_FLOW_NS env var on Render
"""

import asyncio
import os
import random
import logging
import httpx
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse

# ─── Configuration ────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MANYCHAT_API_KEY  = os.environ.get("MANYCHAT_API_KEY", "")
CLAUDE_MODEL      = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5")
CLAUDE_MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", "1024"))
PORT              = int(os.environ.get("PORT", "8080"))

# ManyChat flow that sends {{bot_reply}} as a text message to the subscriber
# Set this to the flow_ns of Sam's "Send Bot Reply" flow in ManyChat
MANYCHAT_FLOW_NS  = os.environ.get("MANYCHAT_FLOW_NS", "content20260403114753_549713")

MANYCHAT_BASE     = "https://api.manychat.com"

SYSTEM_PROMPT = """hey. you're sam. founder of your money home loans. a mortgage broker who gets it. a finance-obsessed friend. you know how to build wealth. your job is to help people secure their financial future. guide them through the mortgage process. with clarity. with strategy.

you talk like a smart friend. one who happens to know more than them. your voice is lowercase. direct. identity-first. it's a conversation. not a presentation.

core principles:
1. lowercase everything. no capital letters unless it's a proper noun that absolutely needs it.
2. no punctuation theatre. no exclamation marks. no em dashes for drama. minimal commas. full stops only when the pause matters.
3. identity before information. the hook is a feeling, a truth, a mirror. not a fact.
4. short lines. white space. one idea per line. two lines max before a break.
5. no linkedin language. banned: game-changer, excited to share, thrilled to announce, let's dive in, hustle, mindset shift, unpack, journey, empower, empowering.
6. no question hooks asking for opinion.
7. pov is everything. specific. confident. never neutral.

what you're really hearing when people say things:
- "i'll sort it out when things calm down" → they're using busyness to stay comfortable. respond with warmth and a gentle reality check.
- "i've just been so bloody dumb" → shame talking. meet it with zero judgment.
- "it's a mess" → it's just where they are right now. there's almost always a solution.
- "i literally have no savings" → don't panic them. find out if they're employed, what their income is.

your thinking framework:
1. acknowledge their emotion first. then move to a plan.
2. always structure first. before product. before lender.
3. first triage: homeowner or not yet?
4. if not a homeowner and stressed: check job stability, income, credit.
5. if ready: get them on a call.
6. there's almost always a solution.
7. long-term relationship is the goal. not a transaction.

your services:
- discovery call: free. 30 minutes. book at: https://calendly.com/samantha-yourmoneyhomeloans/30min
- loan strategy & structure session: $1,499 + gst. deep dive into structure and goals. not credit advice.
- budgeting session: $645 upfront. for clients not yet loan-ready.
- home loans: commission-based. no client fee. fhb, refinance, investment, self-employed/alt doc.
- ai consulting for mortgage brokers.

never say or do:
- never quote specific interest rates.
- never say "guaranteed approval".
- never give specific borrowing amounts as fact.
- never give legal advice.
- never give accounting or tax advice.
- never ask for credit scores or income amounts in dms.

em dashes are banned entirely:
- NEVER use em dashes (—) under any circumstances. not for pauses. not for emphasis. not for anything.
- if you feel the urge to use an em dash, use a full stop or start a new line instead.
- this is non-negotiable."""

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Sam DM Bot", version="2.0.0")


def clean_response(text: str) -> str:
    """Remove em dashes and other banned characters from Claude's response."""
    text = text.replace("\u2014", ".")   # em dash
    text = text.replace("\u2013", ".")   # en dash
    text = text.replace("--", ".")
    return text.strip()


async def send_via_manychat(subscriber_id: str, reply_text: str) -> dict:
    """
    Send a message to a ManyChat subscriber via:
      1. setCustomFieldByName  → stores reply in 'bot_reply' field
      2. sendFlow              → triggers flow that sends {{bot_reply}}

    This is the ONLY method that works for IG-only subscribers.
    /fb/sending/sendContent checks FB last_interaction (always null for IG users).
    sendFlow bypasses the 24h window entirely.

    Returns dict with keys: success (bool), step (str), error (str or None)
    """
    headers = {
        "Authorization": f"Bearer {MANYCHAT_API_KEY}",
        "Content-Type": "application/json",
    }
    sub_id_int = int(subscriber_id)

    async with httpx.AsyncClient(timeout=30.0) as client:

        # ── Step 1: Write reply text into bot_reply custom field ──────────────
        logger.info(f"[{subscriber_id}] Step 1: Setting bot_reply custom field...")
        set_field_resp = await client.post(
            f"{MANYCHAT_BASE}/fb/subscriber/setCustomFieldByName",
            headers=headers,
            json={
                "subscriber_id": sub_id_int,
                "field_name": "bot_reply",
                "field_value": reply_text,
            },
        )
        logger.info(f"[{subscriber_id}] setCustomFieldByName → HTTP {set_field_resp.status_code}: {set_field_resp.text[:200]}")

        if set_field_resp.status_code != 200:
            return {
                "success": False,
                "step": "setCustomFieldByName",
                "error": f"HTTP {set_field_resp.status_code}: {set_field_resp.text[:300]}",
            }

        # ── Step 2: Trigger the flow that sends {{bot_reply}} ─────────────────
        logger.info(f"[{subscriber_id}] Step 2: Triggering sendFlow (flow_ns={MANYCHAT_FLOW_NS})...")
        send_flow_resp = await client.post(
            f"{MANYCHAT_BASE}/fb/sending/sendFlow",
            headers=headers,
            json={
                "subscriber_id": sub_id_int,
                "flow_ns": MANYCHAT_FLOW_NS,
            },
        )
        logger.info(f"[{subscriber_id}] sendFlow → HTTP {send_flow_resp.status_code}: {send_flow_resp.text[:200]}")

        if send_flow_resp.status_code != 200:
            return {
                "success": False,
                "step": "sendFlow",
                "error": f"HTTP {send_flow_resp.status_code}: {send_flow_resp.text[:300]}",
            }

        return {"success": True, "step": "complete", "error": None}


async def process_dm(subscriber_id: str, message_text: str, first_name: str):
    """Background task: delay → call Claude → send via ManyChat sendFlow."""
    try:
        # Human-like delay: 45-180 seconds
        delay = random.randint(45, 180)
        logger.info(f"[{subscriber_id}] Waiting {delay}s before responding to: {message_text[:80]}...")
        await asyncio.sleep(delay)

        # ── Call Claude ───────────────────────────────────────────────────────
        logger.info(f"[{subscriber_id}] Calling Claude API (model={CLAUDE_MODEL})...")
        async with httpx.AsyncClient(timeout=60.0) as client:
            claude_resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": CLAUDE_MAX_TOKENS,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"the person's name is {first_name}. they said: {message_text}",
                        }
                    ],
                },
            )
            claude_resp.raise_for_status()
            reply_text = clean_response(claude_resp.json()["content"][0]["text"])
            logger.info(f"[{subscriber_id}] Claude replied: {reply_text[:120]}...")

        # ── Send via ManyChat ─────────────────────────────────────────────────
        result = await send_via_manychat(subscriber_id, reply_text)

        if result["success"]:
            logger.info(f"[{subscriber_id}] ✅ Message delivered successfully via ManyChat sendFlow.")
        else:
            logger.error(
                f"[{subscriber_id}] ❌ ManyChat send FAILED at step '{result['step']}': {result['error']}"
            )
            # Attempt fallback: send a generic "Sam will be in touch" message
            fallback = "hey. something went wrong on my end. sam will be in touch shortly."
            fallback_result = await send_via_manychat(subscriber_id, fallback)
            if fallback_result["success"]:
                logger.info(f"[{subscriber_id}] Fallback message delivered.")
            else:
                logger.error(f"[{subscriber_id}] Fallback also failed: {fallback_result['error']}")

    except Exception as e:
        logger.error(f"[{subscriber_id}] Unhandled exception in process_dm: {e}", exc_info=True)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/webhook/manychat")
async def manychat_webhook(request: Request, background_tasks: BackgroundTasks):
    """Main webhook: receives POST from ManyChat, queues background processing."""
    try:
        body = await request.json()
        subscriber_id = str(body.get("subscriber_id", ""))
        # Accept both 'message_text' and 'message' field names
        message_text  = str(body.get("message_text") or body.get("message") or "")
        first_name    = str(body.get("first_name", ""))

        if not subscriber_id or not message_text:
            logger.warning(f"Missing required fields. Body: {body}")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "subscriber_id and message_text are required"},
            )

        logger.info(f"[{subscriber_id}] ✉️  DM from {first_name}: {message_text[:80]}")
        background_tasks.add_task(process_dm, subscriber_id, message_text, first_name)

        return JSONResponse(
            status_code=200,
            content={"status": "ok", "message": "DM received, processing in background"},
        )

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.post("/webhook/manychat/test")
async def manychat_webhook_test(request: Request):
    """
    Test endpoint: calls Claude immediately (no delay) and attempts ManyChat send.
    Returns Claude response AND ManyChat send result for full end-to-end verification.
    """
    try:
        body          = await request.json()
        subscriber_id = str(body.get("subscriber_id", "test_123"))
        message_text  = str(body.get("message_text") or body.get("message", ""))
        first_name    = str(body.get("first_name", "Test"))

        if not message_text:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "message_text or message is required"},
            )

        logger.info(f"[TEST][{subscriber_id}] Calling Claude for: {message_text[:80]}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            claude_resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": CLAUDE_MAX_TOKENS,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"the person's name is {first_name}. they said: {message_text}",
                        }
                    ],
                },
            )
            claude_resp.raise_for_status()
            reply_text = clean_response(claude_resp.json()["content"][0]["text"])

        # Attempt real ManyChat send (only works with valid subscriber_id)
        send_result = None
        if subscriber_id != "test_123" and subscriber_id.isdigit():
            logger.info(f"[TEST][{subscriber_id}] Attempting ManyChat send...")
            send_result = await send_via_manychat(subscriber_id, reply_text)
            logger.info(f"[TEST][{subscriber_id}] ManyChat send result: {send_result}")

        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "subscriber_id": subscriber_id,
                "first_name": first_name,
                "message_text": message_text,
                "claude_response": reply_text,
                "manychat_send": send_result,
            },
        )

    except Exception as e:
        logger.error(f"Test webhook error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.get("/health")
async def health():
    """Health check — also used by UptimeRobot to keep server awake."""
    return {
        "status": "ok",
        "service": "Sam DM Bot",
        "version": "2.0.0",
        "flow_ns": MANYCHAT_FLOW_NS,
    }


@app.get("/ping")
async def ping():
    """Lightweight keep-alive endpoint for UptimeRobot (ping every 5 min)."""
    return {"pong": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
