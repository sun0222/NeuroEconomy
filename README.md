# NeuroEconomy

**Autonomous Multi-Agent Intelligence Economy powered by Circle USDC & Claude Agent SDK**

> Built for the Circle Agent Wallet Hackathon 🏆

NeuroEconomy is an autonomous AI system where a Claude-powered orchestrator agent hires specialist research agents, pays each one in USDC via Circle Agent Wallets, synthesizes a professional intelligence brief, and autonomously settles supply chain payments — all with real-time streaming, USDC transactions, and downloadable PDF invoices.

---

## Architecture

```
User (Browser)
    │
    ▼
Next.js 14 Frontend  ──── WebSocket ────►  FastAPI Backend
                                               │
                                     ┌─────────┴──────────┐
                                     │                      │
                             Orchestrator Agent      Settlement Engine
                             (Claude Agent SDK)      (Supply Chain)
                                     │                      │
                          ┌──────────┴──────┐         Tavily Web Search
                          │                 │               │
                    Circle USDC       Specialist       Circle USDC
                    Wallet API         Agents           Payment
                                          │
                                    Tavily Live
                                    Web Search
```

### Specialist Agents (each paid in USDC)

| Agent | Specialty | Payment |
|---|---|---|
| `NewsAggAgent` | Live news aggregation | $1.50 USDC |
| `WebIntelAgent` | Company & startup intelligence | $2.00 USDC |
| `DataAnalysisAgent` | Market size & statistics | $2.50 USDC |
| `PatentSearchAgent` | Patent & technology landscape | $1.50 USDC |
| `SynthesisAgent` | Cross-source synthesis | $2.00 USDC |

---

## Features

- **Autonomous agent economy** — orchestrator discovers, evaluates, pays, and receives deliverables from 5 specialist agents
- **Real Circle USDC payments** — each agent gets paid with an on-chain transfer + transaction hash
- **Live Tavily web search** — all agents pull real-time data from the web (no mocked results)
- **Supply chain settlement** — fetch packaging prices, compare freight quotes, calculate landed cost with import duties, pay supplier in USDC
- **PDF invoice generation** — professional downloadable invoice for every settlement (settled or failed)
- **Insufficient balance detection** — exact shortfall amount shown, transaction blocked safely
- **Real-time WebSocket streaming** — every step streams live to the browser as it happens
- **DEMO_MODE** — full UI flow without consuming Anthropic API credits (great for demos)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python 3.11+, WebSockets |
| AI Orchestration | Anthropic Claude Agent SDK (`claude-sonnet-4-6`) |
| Payments | Circle Agent Wallet API (USDC) |
| Web Search | Tavily API |
| PDF Generation | ReportLab |

---

## Project Structure

```
NeuroEconomy/
├── backend/
│   ├── main.py              # FastAPI app — WebSocket + REST endpoints
│   ├── orchestrator.py      # Claude Agent SDK agentic loop
│   ├── specialist_agents.py # 5 research agents with Tavily search
│   ├── settlement.py        # Supply chain settlement + PDF generation
│   ├── circle_client.py     # Circle API client (real + mock mode)
│   ├── models.py            # Dataclasses: PaymentRecord, OrchestratorState
│   ├── config.py            # Environment variable loader
│   └── requirements.txt
├── frontend/
│   ├── pages/
│   │   ├── index.tsx        # Main UI with research + settlement panels
│   │   └── _app.tsx
│   ├── styles/
│   ├── tailwind.config.js
│   └── package.json
├── .env.example             # Template for required environment variables
└── README.md
```

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/sun0222/NeuroEconomy.git
cd NeuroEconomy
```

### 2. Backend setup

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp ../.env.example backend/.env
```

```env
ANTHROPIC_API_KEY=sk-ant-...          # anthropic.com
CIRCLE_API_KEY=TEST_API_KEY:...       # developers.circle.com (free sandbox)
CIRCLE_MOCK_MODE=true                 # set false to use real Circle API
TAVILY_API_KEY=tvly-dev-...           # app.tavily.com (free tier)

ORCHESTRATOR_WALLET_ID=mock_orch_001
ORCHESTRATOR_ADDRESS=0xYourOrchAddress
USER_WALLET_ADDRESS=0xYourUserAddress

BUDGET_CAP_USDC=12.0
INITIAL_BALANCE_USDC=20.0
DEMO_MODE=true                        # set false to use real Claude API
```

Start the backend:

```bash
python main.py
# → http://localhost:8000
```

### 3. Frontend setup

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

---

## Usage

### Research Mode

1. Open `http://localhost:3000`
2. Type any query (e.g. *"AI agents in European fintech 2025"*)
3. Watch the orchestrator hire 5 agents, pay each in USDC, and deliver a brief in real time

### Supply Chain Settlement

1. Scroll to the **Supply Chain Settlement** panel
2. Enter: product, quantity, ship from, ship to
3. Click **Settle with Supplier**
4. Watch live: prices fetched → freight quoted → landed cost compared → USDC paid → PDF generated
5. Click **Download PDF Invoice**

---

## Environment Modes

| Variable | `true` | `false` |
|---|---|---|
| `DEMO_MODE` | Scripted tool calls, no Claude API credits needed | Full Claude Agent SDK agentic loop |
| `CIRCLE_MOCK_MODE` | In-memory wallet simulation with SHA-256 tx hashes | Real Circle sandbox API calls |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Server status + config |
| `WS` | `/ws/research` | Research orchestrator stream |
| `WS` | `/ws/settle` | Supply chain settlement stream |
| `GET` | `/invoice/{id}/download` | Download PDF invoice |

---

## How Circle Agent Wallet is Used

1. **Orchestrator wallet** holds the research budget in USDC
2. For each specialist agent hired, a Circle transfer is executed (`/transfers`) with amount + destination address
3. Every payment returns a real transaction hash stored in the intelligence brief
4. Unused budget is **refunded** back to the user wallet at the end
5. Supply chain payments go to a **supplier wallet** — blocked with an exact shortfall message if balance is insufficient

---

## License

MIT
