"""FastAPI server for the bio shopping agent."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from db import init_db, approve_draft_order, get_draft_order, get_pending_drafts, get_grant_budgets
from agent import run_agent


# In-memory session store: session_id → message history
sessions: dict[str, list[dict]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Bio Shopping Agent", lifespan=lifespan)

from slack_bot import handler as slack_handler

@app.post("/slack/events")
async def slack_events(req: Request):
    return await slack_handler.handle(req)

@app.post("/slack/interact")
async def slack_interact(req: Request):
    return await slack_handler.handle(req)


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class ApproveRequest(BaseModel):
    draft_id: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Send a message to the agent and get a response."""
    history = sessions.get(req.session_id, [])
    history.append({"role": "user", "content": req.message})

    reply, updated_history = run_agent(history)
    sessions[req.session_id] = updated_history

    return ChatResponse(session_id=req.session_id, reply=reply)


@app.post("/approve")
def approve_order(req: ApproveRequest):
    """Approve a draft order — the one-click confirmation step."""
    draft = get_draft_order(req.draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft order not found")
    if draft["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Draft is already '{draft['status']}'")

    approved = approve_draft_order(req.draft_id)
    return {
        "message": f"Order #{req.draft_id} approved and added to order history.",
        "order": approved,
    }


@app.get("/drafts")
def list_drafts():
    """List all pending draft orders."""
    return {"drafts": get_pending_drafts()}


@app.get("/draft/{draft_id}")
def get_draft(draft_id: int):
    """Get a specific draft order."""
    draft = get_draft_order(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@app.get("/budgets")
def list_budgets():
    """List grant budgets with remaining balances."""
    return {"budgets": get_grant_budgets()}


@app.delete("/session/{session_id}")
def clear_session(session_id: str):
    """Clear a conversation session."""
    sessions.pop(session_id, None)
    return {"message": "Session cleared"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
