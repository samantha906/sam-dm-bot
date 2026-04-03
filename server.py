"""
Sam's Instagram DM Bot — Webhook Server
Receives ManyChat webhook → Calls Claude API → Sends response back to ManyChat
"""

import asyncio
import os
import random
import json
import logging
import httpx
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse

# ─── Configuration (from environment variables) ─────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MANYCHAT_API_KEY = os.environ.get("MANYCHAT_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5")
CLAUDE_MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", "1024"))
PORT = int(os.environ.get("PORT", "8080"))

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

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="Sam DM Bot", version="1.0.0")


def clean_response(text: str) -> str:
    """Post-processing: remove all em dashes from Claude's response."""
    text = text.replace("\u2014", ".")
    text = text.replace("\u2013", ".")
    text = text.replace("--", ".")
    return text


async def process_dm(subscriber_id: str, message_text: str, first_name: str):
    """Background task: delay → call Claude → send response via ManyChat."""
    try:
        # human delay: 45-180 seconds
        delay = random.randint(45, 180)
        logger.info(f"[{subscriber_id}] Delaying {delay}s before responding to: {message_text[:80]}...")
        await asyncio.sleep(delay)

        # call Claude API
        logger.info(f"[{subscriber_id}] Calling Claude API...")
        async with httpx.AsyncClient(timeout=60.0) as client:
            claude_response = await client.post(
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
                            "content": f"the person's name is {first_name}. they said: {message_text}"
                        }
                    ],
                },
            )
            claude_response.raise_for_status()
            claude_data = claude_response.json()
            reply_text = clean_response(claude_data["content"][0]["text"])
            logger.info(f"[{subscriber_id}] Claude replied: {reply_text[:100]}...")

        # send response back to ManyChat
        logger.info(f"[{subscriber_id}] Sending response to ManyChat...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            mc_response = await client.post(
                "https://api.manychat.com/fb/sending/sendContent",
                headers={
                    "Authorization": f"Bearer {MANYCHAT_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "subscriber_id": subscriber_id,
                    "data": {
                        "version": "v2",
                        "content": {
                            "messages": [
                                {
                                    "type": "text",
                                    "text": reply_text
                                }
                            ]
                        }
                    },
                    "message_tag": "ACCOUNT_UPDATE"
                },
            )
            mc_response.raise_for_status()
            logger.info(f"[{subscriber_id}] ManyChat response sent successfully.")

    except Exception as e:
        logger.error(f"[{subscriber_id}] Error processing DM: {e}")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(
                    "https://api.manychat.com/fb/sending/sendContent",
                    headers={
                        "Authorization": f"Bearer {MANYCHAT_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "subscriber_id": subscriber_id,
                        "data": {
                            "version": "v2",
                            "content": {
                                "messages": [
                                    {
                                        "type": "text",
                                        "text": "hey. something went wrong on my end. sam will be in touch shortly."
                                    }
                                ]
                            }
                        },
                        "message_tag": "ACCOUNT_UPDATE"
                    },
                )
                logger.info(f"[{subscriber_id}] Fallback message sent.")
        except Exception as fallback_error:
            logger.error(f"[{subscriber_id}] Fallback message also failed: {fallback_error}")


@app.post("/webhook/manychat")
async def manychat_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receives POST from ManyChat with: subscriber_id, message_text, first_name"""
    try:
        body = await request.json()
        subscriber_id = str(body.get("subscriber_id", ""))
        # Accept both 'message_text' and 'message' field names from ManyChat
        message_text = str(body.get("message_text") or body.get("message") or "")
        first_name = str(body.get("first_name", ""))

        if not subscriber_id or not message_text:
            logger.warning(f"Missing required fields. Body: {body}")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "subscriber_id and message_text are required"}
            )

        logger.info(f"[{subscriber_id}] Received DM from {first_name}: {message_text[:80]}")
        background_tasks.add_task(process_dm, subscriber_id, message_text, first_name)

        return JSONResponse(
            status_code=200,
            content={"status": "ok", "message": "DM received, processing in background"}
        )

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


@app.post("/webhook/manychat/test")
async def manychat_webhook_test(request: Request):
    """Test endpoint: calls Claude immediately (no delay) and returns the response."""
    try:
        body = await request.json()
        subscriber_id = str(body.get("subscriber_id", "test_123"))
        message_text = str(body.get("message_text", ""))
        first_name = str(body.get("first_name", "Test"))

        if not message_text:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "message_text is required"}
            )

        logger.info(f"[TEST] Calling Claude for: {message_text[:80]}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            claude_response = await client.post(
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
                            "content": f"the person's name is {first_name}. they said: {message_text}"
                        }
                    ],
                },
            )
            claude_response.raise_for_status()
            claude_data = claude_response.json()
            reply_text = clean_response(claude_data["content"][0]["text"])

        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "subscriber_id": subscriber_id,
                "first_name": first_name,
                "message_text": message_text,
                "claude_response": reply_text
            }
        )

    except Exception as e:
        logger.error(f"Test webhook error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Sam DM Bot", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
