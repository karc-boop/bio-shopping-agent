# Bio Material Shopping Agent

An AI-powered procurement assistant for university research labs, built with Claude and deployable as a Slack bot. Researchers can search, compare, and order biological materials through natural conversation.

## Features

- **Conversational ordering** — describe what you need in plain language
- **Scientific Score** — products ranked by peer-reviewed citation count, so you pick the most reproducible reagent
- **Grant budget tracking** — real-time balance per grant code, with warnings before you overspend
- **Draft order workflow** — agent never auto-places orders; every order requires explicit approval
- **Slack-native** — works via DM or @mention in any channel

![BioShop comparing two Matrigel products with Scientific Score](assets/fig_comparison.png)

## Project Structure

```
bio-shopping-agent/
├── main.py          # FastAPI server + REST endpoints
├── agent.py         # Claude agentic loop (tool use)
├── tools.py         # Tool definitions and implementations
├── db.py            # SQLite storage (lab profile, orders, grant budgets)
├── mock_data.py     # Product catalog with Scientific Scores
├── slack_bot.py     # Slack Bolt bot (events + interactive buttons)
└── requirements.txt
```

## Setup

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Set environment variables

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
```

Then load it:

```bash
source .env
```

### 3. Start the server

```bash
python3 -m uvicorn main:app --reload --port 8001
```

### 4. Expose locally with ngrok (for Slack webhook)

```bash
ngrok http 8001
```

## Slack App Configuration

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. **OAuth & Permissions** → Bot Token Scopes: `chat:write`, `im:history`, `app_mentions:read`
3. Install app to workspace → copy the `xoxb-` Bot Token
4. **Event Subscriptions** → Request URL: `https://<ngrok-url>/slack/events`
   - Subscribe to bot events: `message.im`, `app_mention`
5. **Interactivity & Shortcuts** → Request URL: `https://<ngrok-url>/slack/interact`
6. Copy Signing Secret from **Basic Information → App Credentials**

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/chat` | Send a message to the agent |
| GET | `/drafts` | List pending draft orders |
| GET | `/draft/{id}` | Get a specific draft |
| POST | `/approve` | Approve a draft order |
| GET | `/budgets` | View grant balances |
| DELETE | `/session/{id}` | Clear a conversation session |

Interactive docs available at `http://localhost:8001/docs`.

## Usage

### Slack

DM the bot or @mention it in a channel:

```
I need to order Matrigel for organoid culture, charge NIH grant
```

The bot will search the catalog, compare options with Scientific Scores, check your grant balance, and present a draft order with Approve / Reject buttons.

### REST API

```bash
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "lab1", "message": "I need BSA for western blot"}'
```

## Seed Data

The lab profile is pre-seeded with:
- **Lab**: Chen Lab – Bioengineering Dept, University of California
- **PI**: Prof. Sarah Chen
- **Grants**: NIH-R01-2023-BIO ($15,000), NSF-MCB-2024 ($8,000), DOD-CDMRP-2024 ($5,000)
- **Products**: 8 common bio materials (Matrigel, BSA, FBS, DMEM, Collagen, Trypsin)
