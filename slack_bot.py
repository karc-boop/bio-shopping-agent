"""Slack bot interface for the bio shopping agent.

Environment variables required:
    SLACK_BOT_TOKEN      — Bot User OAuth Token (xoxb-...)
    SLACK_SIGNING_SECRET — Used to verify requests from Slack

Slack app configuration:
    Event Subscriptions  → Request URL: https://<your-host>/slack/events
                           Subscribe to: message.im, app_mention
    Interactivity        → Request URL: https://<your-host>/slack/interact
    OAuth Scopes (Bot)   → chat:write, im:history, app_mentions:read, channels:history
"""

import os
import re
import asyncio
from typing import Optional

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

from agent import run_agent
from db import approve_draft_order, reject_draft_order, get_draft_order


app = AsyncApp(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)

handler = AsyncSlackRequestHandler(app)

# Slack user_id → conversation history (in-memory, same as web sessions)
_sessions: dict[str, list] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_draft_id(text: str) -> Optional[int]:
    """Return draft order ID if the agent text mentions one, else None."""
    m = re.search(r"[Dd]raft order #(\d+)", text)
    return int(m.group(1)) if m else None


def _md_to_mrkdwn(text: str) -> str:
    """Convert basic markdown to Slack mrkdwn."""
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)   # **bold** → *bold*
    return text


def _build_draft_blocks(draft_id: int, agent_text: str) -> list:
    """Build Block Kit blocks for a draft order: summary card + Approve/Reject buttons."""
    draft = get_draft_order(draft_id)
    repro_warning = ""
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _md_to_mrkdwn(agent_text)},
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Product:*\n{draft['product_name']}"},
                {"type": "mrkdwn", "text": f"*Supplier:*\n{draft['supplier']}"},
                {"type": "mrkdwn", "text": f"*Qty:*\n{draft['quantity']} × ${draft['unit_price_usd']:.2f}"},
                {"type": "mrkdwn", "text": f"*Total:*\n*${draft['total_price_usd']:.2f}*"},
                {"type": "mrkdwn", "text": f"*Grant:*\n{draft['grant_code'] or '—'}"},
                {"type": "mrkdwn", "text": f"*Catalog #:*\n{draft['catalog_number']}"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "value": str(draft_id),
                    "action_id": "approve_draft",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "value": str(draft_id),
                    "action_id": "reject_draft",
                },
            ],
        },
    ]
    return blocks


def _build_text_blocks(text: str) -> list:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": _md_to_mrkdwn(text)}}]


# ── Core message handler ───────────────────────────────────────────────────────

async def _handle_user_message(user_id: str, text: str, say, client, channel: str):
    """Shared logic for DM messages and channel @mentions."""
    # Post "Thinking…" immediately — Slack expects a fast response
    thinking = await say("_Thinking…_")

    try:
        session_key = f"slack_{user_id}"
        history = _sessions.get(session_key, [])
        history.append({"role": "user", "content": text})

        # run_agent is synchronous (Anthropic SDK); run in thread pool
        reply, updated_history = await asyncio.to_thread(run_agent, history)
        _sessions[session_key] = updated_history

        draft_id = _extract_draft_id(reply)
        blocks = _build_draft_blocks(draft_id, reply) if draft_id else _build_text_blocks(reply)

        await client.chat_update(
            channel=channel,
            ts=thinking["ts"],
            text=reply,
            blocks=blocks,
        )
    except Exception as e:
        await client.chat_update(
            channel=channel,
            ts=thinking["ts"],
            text=f"Error: {e}",
        )


@app.event("message")
async def handle_dm(event, say, client):
    """Handle direct messages to the bot."""
    # Only process DMs (channel_type == "im"); ignore bot messages and subtypes
    if event.get("channel_type") != "im":
        return
    if event.get("bot_id") or event.get("subtype"):
        return

    text = event.get("text", "").strip()
    if not text:
        return

    await _handle_user_message(
        user_id=event["user"],
        text=text,
        say=say,
        client=client,
        channel=event["channel"],
    )


@app.event("app_mention")
async def handle_mention(event, say, client):
    """Handle @mentions of the bot in channels."""
    # Strip the bot mention prefix (<@UXXXXXXX>) from the text
    text = re.sub(r"<@[A-Z0-9]+>\s*", "", event.get("text", "")).strip()
    if not text:
        return

    await _handle_user_message(
        user_id=event["user"],
        text=text,
        say=say,
        client=client,
        channel=event["channel"],
    )


# ── Interactive component handlers ────────────────────────────────────────────

@app.action("approve_draft")
async def handle_approve(ack, body, client):
    await ack()

    draft_id = int(body["actions"][0]["value"])
    channel = body["container"]["channel_id"]
    message_ts = body["container"]["message_ts"]
    user_id = body["user"]["id"]

    approved = approve_draft_order(draft_id)
    if not approved:
        await client.chat_postMessage(
            channel=channel,
            text=f"<@{user_id}> Draft #{draft_id} could not be approved — it may have already been processed.",
        )
        return

    confirmed_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Order #{draft_id} approved* :white_check_mark:\n"
                    f"*{approved['product_name']}* × {approved['quantity']} — "
                    f"*${approved['total_price_usd']:.2f}*\n"
                    f"Grant: `{approved['grant_code'] or '—'}`\n"
                    f"_Charged to grant budget and added to order history._"
                ),
            },
        }
    ]
    await client.chat_update(
        channel=channel,
        ts=message_ts,
        text=f"Order #{draft_id} approved.",
        blocks=confirmed_blocks,
    )


@app.action("reject_draft")
async def handle_reject(ack, body, client):
    await ack()

    draft_id = int(body["actions"][0]["value"])
    channel = body["container"]["channel_id"]
    message_ts = body["container"]["message_ts"]
    user_id = body["user"]["id"]

    reject_draft_order(draft_id)

    rejected_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Draft #{draft_id} rejected* :x:\n"
                    f"<@{user_id}>, let me know how you'd like to adjust — "
                    f"different quantity, supplier, or grant code?"
                ),
            },
        }
    ]
    await client.chat_update(
        channel=channel,
        ts=message_ts,
        text=f"Draft #{draft_id} rejected.",
        blocks=rejected_blocks,
    )
