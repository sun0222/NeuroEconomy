import { useState, useRef, useCallback, useEffect } from "react";
import Head from "next/head";

// ------------------------------------------------------------------ //
// Types
// ------------------------------------------------------------------ //

interface Payment {
  agent_name: string;
  amount_usdc: number;
  transaction_hash: string;
  to_address: string;
  query: string;
  status: string;
  timestamp: string;
}

interface Evaluation {
  agent_name: string;
  relevance_score: number;
  reasoning: string;
  will_hire: boolean;
}

interface Brief {
  title: string;
  executive_summary: string;
  key_findings: string[];
  recommendations: string[];
  data_sources: string[];
}

interface ActivityEvent {
  id: number;
  type: string;
  label: string;
  detail?: string;
  time: string;
  color: string;
}

// Settlement types
interface PricingOption {
  supplier: string;
  material: string;
  unit_price: number;
  moq: number;
  lead_time: number;
  country: string;
}

interface FreightQuote {
  carrier: string;
  service: string;
  cost_usd: number;
  transit_days: number;
}

interface LandedRow {
  rank: number;
  supplier: string;
  unit_price: number;
  product_cost: number;
  freight_cost: number;
  duty: number;
  total: number;
  per_unit: number;
  recommended: boolean;
}

interface SettlementResult {
  invoice_id: string;
  status: string;
  amount_usdc: number;
  transaction_hash: string;
  supplier: string;
  total_landed: number;
  balance_before: number;
  balance_after: number;
  download_url: string;
  error: string | null;
}

// ------------------------------------------------------------------ //
// Helpers
// ------------------------------------------------------------------ //

const AGENT_COLORS: Record<string, string> = {
  NewsAggAgent: "text-sky-400",
  WebIntelAgent: "text-violet-400",
  DataAnalysisAgent: "text-emerald-400",
  PatentSearchAgent: "text-amber-400",
  SynthesisAgent: "text-pink-400",
};

const AGENT_ICONS: Record<string, string> = {
  NewsAggAgent: "📰",
  WebIntelAgent: "🌐",
  DataAnalysisAgent: "📊",
  PatentSearchAgent: "⚖️",
  SynthesisAgent: "🧠",
};

function shortHash(hash: string) {
  if (!hash) return "";
  return `${hash.slice(0, 10)}...${hash.slice(-6)}`;
}

function now() {
  return new Date().toLocaleTimeString("en-US", { hour12: false });
}

// ------------------------------------------------------------------ //
// Sub-components
// ------------------------------------------------------------------ //

function BudgetMeter({ spent, cap }: { spent: number; cap: number }) {
  const pct = Math.min((spent / cap) * 100, 100);
  const color =
    pct < 50 ? "bg-emerald-500" : pct < 80 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="w-full">
      <div className="flex justify-between text-xs text-slate-400 mb-1">
        <span>Spent: <span className="text-white font-bold">${spent.toFixed(2)}</span></span>
        <span>Cap: <span className="text-white">${cap.toFixed(2)}</span></span>
      </div>
      <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-slate-500 mt-1 text-right">{pct.toFixed(1)}% of budget used</p>
    </div>
  );
}

function PaymentCard({ payment, index }: { payment: Payment; index: number }) {
  const icon = AGENT_ICONS[payment.agent_name] ?? "💳";
  const color = AGENT_COLORS[payment.agent_name] ?? "text-slate-300";
  return (
    <div className="animate-slide-up bg-slate-800 border border-slate-700 rounded-xl p-3 space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">#{index + 1}</span>
        <span className="text-xs font-mono text-emerald-400 font-bold">
          +${payment.amount_usdc.toFixed(2)} USDC
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-lg">{icon}</span>
        <span className={`font-semibold text-sm ${color}`}>{payment.agent_name}</span>
      </div>
      <p className="text-xs text-slate-400 italic truncate">{payment.query}</p>
      <div className="flex items-center gap-1 mt-1">
        <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" />
        <span className="text-xs text-slate-500 font-mono">{shortHash(payment.transaction_hash)}</span>
        <button
          onClick={() => navigator.clipboard.writeText(payment.transaction_hash)}
          className="ml-auto text-xs text-slate-600 hover:text-slate-300 transition"
          title="Copy tx hash"
        >
          copy
        </button>
      </div>
    </div>
  );
}

function EvalRow({ eval: e }: { eval: Evaluation }) {
  const icon = e.will_hire ? "✅" : "⏭️";
  const scorePct = Math.round(e.relevance_score * 100);
  return (
    <div className="flex items-start gap-2 py-2 border-b border-slate-800 last:border-0 animate-fade-in">
      <span className="text-sm mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-200">{e.agent_name}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded-full font-bold ${e.will_hire ? "bg-emerald-900 text-emerald-300" : "bg-slate-700 text-slate-400"}`}>
            {scorePct}%
          </span>
        </div>
        <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{e.reasoning}</p>
      </div>
    </div>
  );
}

function ActivityFeed({ events }: { events: ActivityEvent[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [events]);

  return (
    <div
      ref={ref}
      className="h-64 overflow-y-auto scrollbar-thin space-y-1 pr-1"
    >
      {events.length === 0 && (
        <p className="text-slate-600 text-sm text-center mt-8">Activity will appear here...</p>
      )}
      {events.map((e) => (
        <div key={e.id} className="flex items-start gap-2 animate-fade-in">
          <span className="text-xs text-slate-600 font-mono mt-0.5 shrink-0">{e.time}</span>
          <span className={`text-xs ${e.color} leading-5`}>{e.label}</span>
          {e.detail && (
            <span className="text-xs text-slate-500 truncate">{e.detail}</span>
          )}
        </div>
      ))}
    </div>
  );
}

function BriefSection({ brief }: { brief: Brief }) {
  return (
    <div className="animate-slide-up space-y-5">
      <div>
        <h2 className="text-2xl font-bold text-white">{brief.title}</h2>
        <p className="mt-2 text-slate-300 leading-relaxed">{brief.executive_summary}</p>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Key Findings
        </h3>
        <ul className="space-y-2">
          {brief.key_findings.map((f, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-slate-200">
              <span className="text-emerald-400 mt-0.5 shrink-0">▸</span>
              {f}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Recommendations
        </h3>
        <ol className="space-y-2">
          {brief.recommendations.map((r, i) => (
            <li key={i} className="flex items-start gap-3 text-sm text-slate-200">
              <span className="text-violet-400 font-bold shrink-0">{i + 1}.</span>
              {r}
            </li>
          ))}
        </ol>
      </div>

      {brief.data_sources?.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2">
            Data Sources Purchased
          </h3>
          <div className="flex flex-wrap gap-2">
            {brief.data_sources.map((s, i) => (
              <span key={i} className="text-xs bg-slate-800 border border-slate-700 rounded-full px-3 py-1 text-slate-300">
                {s}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ //
// Main Page
// ------------------------------------------------------------------ //

export default function Home() {
  const [query, setQuery] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [isDone, setIsDone] = useState(false);

  const [balance, setBalance] = useState(20.0);
  const [spent, setSpent] = useState(0);
  const [budgetCap, setBudgetCap] = useState(12.0);
  const [refunded, setRefunded] = useState<number | null>(null);

  const [payments, setPayments] = useState<Payment[]>([]);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const eventCounter = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);

  const addEvent = useCallback((label: string, color = "text-slate-300", detail?: string) => {
    eventCounter.current += 1;
    const ev: ActivityEvent = {
      id: eventCounter.current,
      type: "log",
      label,
      detail,
      time: now(),
      color,
    };
    setEvents((prev) => [...prev, ev]);
  }, []);

  const handleEvent = useCallback(
    (type: string, data: Record<string, unknown>) => {
      switch (type) {
        case "started":
          setBalance(data.initial_balance as number);
          setBudgetCap(data.budget_cap as number);
          addEvent("Research started", "text-brand");
          break;

        case "balance_checked":
          setBalance(data.balance as number);
          addEvent(
            `Wallet checked: $${(data.balance as number).toFixed(2)} USDC`,
            "text-usdc",
            `0x${String(data.wallet_address).slice(2, 10)}...`
          );
          break;

        case "agents_discovered":
          addEvent(
            `Discovered ${Object.keys(data.agents as object).length} agents on Circle Marketplace`,
            "text-violet-400"
          );
          break;

        case "agent_evaluated": {
          const e = data as unknown as Evaluation;
          setEvaluations((prev) => [...prev, e]);
          addEvent(
            `${e.will_hire ? "✅ Hiring" : "⏭️  Skipping"} ${e.agent_name} (${Math.round(e.relevance_score * 100)}%)`,
            e.will_hire ? "text-emerald-400" : "text-slate-500"
          );
          break;
        }

        case "payment_initiating":
          addEvent(
            `Paying ${data.agent_name as string} $${(data.amount_usdc as number).toFixed(2)} USDC...`,
            "text-amber-400"
          );
          break;

        case "payment_confirmed": {
          setSpent(data.total_spent as number);
          setBalance(data.remaining_balance as number);
          const p: Payment = {
            agent_name: data.agent_name as string,
            amount_usdc: data.amount_usdc as number,
            transaction_hash: data.transaction_hash as string,
            to_address: data.to_address as string,
            query: "",
            status: "CONFIRMED",
            timestamp: new Date().toISOString(),
          };
          setPayments((prev) => [...prev, p]);
          addEvent(
            `Payment confirmed: $${(data.amount_usdc as number).toFixed(2)} → ${data.agent_name as string}`,
            "text-emerald-400",
            shortHash(data.transaction_hash as string)
          );
          break;
        }

        case "agent_querying":
          addEvent(`Querying ${data.agent_name as string}...`, "text-sky-400");
          break;

        case "agent_responded":
          addEvent(
            `${data.agent_name as string} returned ${data.findings_count as number} findings (confidence: ${Math.round((data.confidence as number) * 100)}%)`,
            "text-slate-300"
          );
          break;

        case "budget_exceeded":
          addEvent(
            `Budget cap reached — skipping ${data.agent_name as string}`,
            "text-red-400"
          );
          break;

        case "refund_sent":
          setRefunded(data.amount_usdc as number);
          addEvent(
            `Refund sent: $${(data.amount_usdc as number).toFixed(2)} USDC → user wallet`,
            "text-usdc",
            shortHash(data.transaction_hash as string)
          );
          break;

        case "brief_ready":
          addEvent(`Brief ready: "${data.title as string}"`, "text-brand");
          break;

        case "finished":
          addEvent(
            `Done. Total spent: $${(data.total_spent as number).toFixed(2)} | Payments: ${data.payments_count as number}`,
            "text-emerald-300"
          );
          break;

        case "complete": {
          const result = data as {
            brief: Brief;
            payments: Payment[];
            evaluations: Evaluation[];
            total_spent: number;
            refunded: number;
          };
          if (result.brief) setBrief(result.brief);
          if (result.payments?.length) setPayments(result.payments);
          if (result.evaluations?.length) setEvaluations(result.evaluations);
          setSpent(result.total_spent);
          setRefunded(result.refunded);
          setIsRunning(false);
          setIsDone(true);
          break;
        }

        case "error":
          setError(data.message as string);
          setIsRunning(false);
          break;
      }
    },
    [addEvent]
  );

  const startResearch = useCallback(() => {
    if (!query.trim() || isRunning) return;

    // Reset state
    setIsRunning(true);
    setIsDone(false);
    setBrief(null);
    setPayments([]);
    setEvaluations([]);
    setEvents([]);
    setSpent(0);
    setRefunded(null);
    setError(null);

    const backendHttp = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    const backendWs = backendHttp.replace(/^http/, "ws");
    const ws = new WebSocket(`${backendWs}/ws/research`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ query }));
    };

    ws.onmessage = (msg) => {
      try {
        const { type, data } = JSON.parse(msg.data);
        handleEvent(type, data);
      } catch (e) {
        console.error("WS parse error", e);
      }
    };

    ws.onerror = () => {
      setError("Could not connect to backend. Make sure it is running on port 8000.");
      setIsRunning(false);
    };

    ws.onclose = () => {
      setIsRunning(false);
    };
  }, [query, isRunning, handleEvent]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      startResearch();
    }
  };

  return (
    <>
      <Head>
        <title>NeuroEconomy — Autonomous Agent Intelligence Economy</title>
        <meta name="description" content="AI agent that hires and pays specialist agents using Circle USDC wallets" />
      </Head>

      <div className="min-h-screen bg-[#0f1117] text-slate-100 p-4 md:p-8">
        {/* Header */}
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-3xl font-bold bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent">
                NeuroEconomy
              </h1>
              <p className="text-slate-500 text-sm mt-1">
                Autonomous multi-agent intelligence economy powered by Circle USDC
              </p>
            </div>
            <div className="text-right">
              <div className="text-xs text-slate-500">Wallet Balance</div>
              <div className="text-2xl font-bold text-usdc">
                ${balance.toFixed(2)} <span className="text-sm font-normal text-slate-400">USDC</span>
              </div>
            </div>
          </div>

          {/* Query input */}
          <div className="bg-slate-900 border border-slate-700 rounded-2xl p-4 mb-6">
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isRunning}
              placeholder="What do you need to research? e.g. 'Research sustainable packaging startups in Germany for a potential acquisition'"
              className="w-full bg-transparent text-slate-100 placeholder-slate-600 text-sm resize-none outline-none min-h-[60px] leading-relaxed"
              rows={2}
            />
            <div className="flex items-center justify-between mt-3">
              <p className="text-xs text-slate-600">Press Enter or click Research to start</p>
              <button
                onClick={startResearch}
                disabled={isRunning || !query.trim()}
                className="px-6 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition-all duration-200 flex items-center gap-2"
              >
                {isRunning ? (
                  <>
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Researching...
                  </>
                ) : (
                  "Research"
                )}
              </button>
            </div>
          </div>

          {error && (
            <div className="bg-red-950 border border-red-800 rounded-xl p-4 mb-6 text-red-300 text-sm">
              {error}
            </div>
          )}

          {/* Main grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left — Activity + Evaluations */}
            <div className="space-y-5">
              {/* Budget meter */}
              <div className="bg-slate-900 border border-slate-700 rounded-2xl p-4">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                  Budget Tracker
                </h3>
                <BudgetMeter spent={spent} cap={budgetCap} />
                {refunded !== null && (
                  <div className="mt-3 p-2 bg-usdc/10 border border-usdc/20 rounded-lg text-center">
                    <span className="text-xs text-usdc font-semibold">
                      ${refunded.toFixed(2)} USDC refunded to user
                    </span>
                  </div>
                )}
              </div>

              {/* Live activity */}
              <div className="bg-slate-900 border border-slate-700 rounded-2xl p-4">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                  Live Activity
                </h3>
                <ActivityFeed events={events} />
              </div>

              {/* Agent evaluations */}
              {evaluations.length > 0 && (
                <div className="bg-slate-900 border border-slate-700 rounded-2xl p-4">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                    Agent Evaluations
                  </h3>
                  <div>
                    {evaluations.map((e, i) => (
                      <EvalRow key={i} eval={e} />
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Middle — Spend Ledger */}
            <div className="bg-slate-900 border border-slate-700 rounded-2xl p-4">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Spend Ledger
                </h3>
                <span className="text-xs text-slate-500">{payments.length} transactions</span>
              </div>

              {payments.length === 0 ? (
                <div className="text-center text-slate-600 text-sm mt-16">
                  <div className="text-4xl mb-2">💳</div>
                  <p>Payments will appear here</p>
                </div>
              ) : (
                <div className="space-y-3 overflow-y-auto max-h-[600px] scrollbar-thin pr-1">
                  {payments.map((p, i) => (
                    <PaymentCard key={i} payment={p} index={i} />
                  ))}
                  {isDone && (
                    <div className="mt-4 p-3 bg-emerald-950 border border-emerald-800 rounded-xl text-center animate-fade-in">
                      <div className="text-lg font-bold text-emerald-400">${spent.toFixed(2)} USDC</div>
                      <div className="text-xs text-emerald-600">total spent across {payments.length} agent payments</div>
                      {refunded !== null && (
                        <div className="text-xs text-usdc mt-1">${refunded.toFixed(2)} USDC refunded</div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Right — Intelligence Brief */}
            <div className="bg-slate-900 border border-slate-700 rounded-2xl p-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">
                Intelligence Brief
              </h3>

              {!brief ? (
                <div className="text-center text-slate-600 text-sm mt-16">
                  <div className="text-4xl mb-2">📋</div>
                  <p>Your research brief will appear here</p>
                  {isRunning && (
                    <div className="mt-4 flex justify-center">
                      <div className="w-6 h-6 border-2 border-slate-700 border-t-indigo-500 rounded-full animate-spin" />
                    </div>
                  )}
                </div>
              ) : (
                <div className="overflow-y-auto max-h-[680px] scrollbar-thin pr-1">
                  <BriefSection brief={brief} />
                </div>
              )}
            </div>
          </div>

          {/* ── Settlement Panel ── */}
          <SettlementPanel />

          {/* Footer */}
          <div className="mt-8 text-center text-xs text-slate-700">
            Powered by Circle Agent Wallet + Tavily + Claude Agent SDK
            {" · "}
            {payments.length > 0 && `${payments.length} USDC payments executed`}
          </div>
        </div>
      </div>
    </>
  );
}

// ================================================================== //
// Settlement Panel Component
// ================================================================== //

function SettlementPanel() {
  const [product, setProduct]       = useState("");
  const [quantity, setQuantity]     = useState("5000");
  const [origin, setOrigin]         = useState("Germany");
  const [destination, setDestination] = useState("United Kingdom");
  const [isRunning, setIsRunning]   = useState(false);
  const [stepLabel, setStepLabel]   = useState("");

  const [prices, setPrices]         = useState<PricingOption[]>([]);
  const [freight, setFreight]       = useState<FreightQuote[]>([]);
  const [landedRows, setLandedRows] = useState<LandedRow[]>([]);
  const [balanceInfo, setBalanceInfo] = useState<{balance:number;required:number;sufficient:boolean}|null>(null);
  const [result, setResult]         = useState<SettlementResult|null>(null);
  const [settleError, setSettleError] = useState<string|null>(null);

  const wsRef = useRef<WebSocket|null>(null);

  const startSettlement = useCallback(() => {
    if (!product.trim() || isRunning) return;
    setIsRunning(true);
    setStepLabel("Connecting...");
    setPrices([]); setFreight([]); setLandedRows([]);
    setBalanceInfo(null); setResult(null); setSettleError(null);

    const backendHttp2 = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    const backendWs2 = backendHttp2.replace(/^http/, "ws");
    const ws = new WebSocket(`${backendWs2}/ws/settle`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ product, quantity: parseInt(quantity), origin, destination }));
    };

    ws.onmessage = (msg) => {
      const { type, data } = JSON.parse(msg.data);

      if (type === "step")
        setStepLabel(data.label);

      else if (type === "prices_fetched")
        setPrices(data.options);

      else if (type === "freight_fetched")
        setFreight(data.quotes);

      else if (type === "landed_cost_calculated")
        setLandedRows(data.rows);

      else if (type === "balance_checked")
        setBalanceInfo({ balance: data.balance, required: data.required, sufficient: data.sufficient });

      else if (type === "insufficient_balance")
        setSettleError(`Insufficient balance. Required: $${data.required.toFixed(2)} USDC | Available: $${data.balance.toFixed(2)} USDC | Shortfall: $${data.shortfall.toFixed(2)} USDC`);

      else if (type === "settlement_complete") {
        setResult(data as SettlementResult);
        setIsRunning(false);
        setStepLabel("");
      }
      else if (type === "error") {
        setSettleError(data.message);
        setIsRunning(false);
        setStepLabel("");
      }
    };

    ws.onerror = () => {
      setSettleError("Connection error. Make sure backend is running on port 8000.");
      setIsRunning(false);
    };

    ws.onclose = () => setIsRunning(false);
  }, [product, quantity, origin, destination, isRunning]);

  return (
    <div className="mt-8 bg-slate-900 border border-slate-700 rounded-2xl p-6">
      {/* Section header */}
      <div className="flex items-center gap-3 mb-6">
        <span className="text-2xl">📦</span>
        <div>
          <h2 className="text-lg font-bold text-white">Supply Chain Settlement</h2>
          <p className="text-xs text-slate-500">
            Fetch live prices → compare landed cost → settle with supplier in USDC → download PDF invoice
          </p>
        </div>
      </div>

      {/* Inputs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1">Product / Material</label>
          <input
            value={product}
            onChange={e => setProduct(e.target.value)}
            placeholder="e.g. kraft paper boxes"
            disabled={isRunning}
            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-600 outline-none focus:border-indigo-500 transition"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Quantity (units)</label>
          <input
            type="number"
            value={quantity}
            onChange={e => setQuantity(e.target.value)}
            disabled={isRunning}
            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500 transition"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Ship From</label>
          <input
            value={origin}
            onChange={e => setOrigin(e.target.value)}
            disabled={isRunning}
            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500 transition"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Ship To</label>
          <input
            value={destination}
            onChange={e => setDestination(e.target.value)}
            disabled={isRunning}
            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-indigo-500 transition"
          />
        </div>
      </div>

      <button
        onClick={startSettlement}
        disabled={isRunning || !product.trim()}
        className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-sm transition flex items-center gap-2"
      >
        {isRunning
          ? <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />{stepLabel || "Processing..."}</>
          : "Settle with Supplier"}
      </button>

      {/* Error */}
      {settleError && !result && (
        <div className="mt-4 p-4 bg-red-950 border border-red-700 rounded-xl text-red-300 text-sm">
          <span className="font-bold">Transaction Failed</span> — {settleError}
        </div>
      )}

      {/* Results grid */}
      {(prices.length > 0 || landedRows.length > 0 || result) && (
        <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Packaging prices */}
          {prices.length > 0 && (
            <div className="bg-slate-800 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">📋 Packaging Prices</h3>
              <div className="space-y-2">
                {prices.map((p, i) => (
                  <div key={i} className="flex justify-between items-center border-b border-slate-700 pb-2 last:border-0">
                    <div>
                      <p className="text-sm font-medium text-slate-200">{p.supplier}</p>
                      <p className="text-xs text-slate-500">MOQ {p.moq.toLocaleString()} · {p.lead_time}d lead</p>
                    </div>
                    <span className="text-emerald-400 font-bold text-sm">${p.unit_price.toFixed(4)}/unit</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Freight quotes */}
          {freight.length > 0 && (
            <div className="bg-slate-800 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">🚢 Freight Quotes</h3>
              <div className="space-y-2">
                {freight.map((f, i) => (
                  <div key={i} className="flex justify-between items-center border-b border-slate-700 pb-2 last:border-0">
                    <div>
                      <p className="text-sm font-medium text-slate-200">{f.carrier}</p>
                      <p className="text-xs text-slate-500">{f.service} · {f.transit_days}d transit</p>
                    </div>
                    <span className="text-sky-400 font-bold text-sm">${f.cost_usd.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Balance check */}
          {balanceInfo && (
            <div className="bg-slate-800 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">💳 Balance Check</h3>
              <div className="space-y-2">
                <div className="flex justify-between">
                  <span className="text-xs text-slate-400">Wallet Balance</span>
                  <span className="text-sm font-bold text-usdc">${balanceInfo.balance.toFixed(2)} USDC</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-xs text-slate-400">Required</span>
                  <span className="text-sm font-bold text-white">${balanceInfo.required.toFixed(2)} USDC</span>
                </div>
                <div className={`text-center text-xs font-bold py-1 rounded-lg mt-2 ${balanceInfo.sufficient ? "bg-emerald-900 text-emerald-300" : "bg-red-900 text-red-300"}`}>
                  {balanceInfo.sufficient ? "✓ Sufficient Balance" : "✗ Insufficient Balance"}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Landed cost table */}
      {landedRows.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">⚖️ Landed Cost Comparison</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-indigo-600 text-white">
                  {["#", "Supplier", "Unit Price", "Product Cost", "Freight", "Duties", "Total Landed", "Per Unit"].map(h => (
                    <th key={h} className="px-3 py-2 text-left font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {landedRows.map((r, i) => (
                  <tr key={i} className={r.recommended ? "bg-emerald-950 border border-emerald-700" : i%2===0 ? "bg-slate-800" : "bg-slate-750"}>
                    <td className="px-3 py-2">{r.recommended ? "★" : r.rank}</td>
                    <td className="px-3 py-2 font-medium">{r.supplier}{r.recommended && <span className="ml-2 text-emerald-400 text-xs">BEST</span>}</td>
                    <td className="px-3 py-2">${r.unit_price.toFixed(4)}</td>
                    <td className="px-3 py-2">${r.product_cost.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
                    <td className="px-3 py-2">${r.freight_cost.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
                    <td className="px-3 py-2">${r.duty.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
                    <td className={`px-3 py-2 font-bold ${r.recommended ? "text-emerald-400" : "text-white"}`}>
                      ${r.total.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
                    </td>
                    <td className="px-3 py-2">${r.per_unit.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Settlement result */}
      {result && (
        <div className={`mt-4 rounded-xl p-5 border ${result.status === "SETTLED" ? "bg-emerald-950 border-emerald-700" : "bg-red-950 border-red-700"}`}>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className={`text-lg font-bold mb-1 ${result.status === "SETTLED" ? "text-emerald-300" : "text-red-300"}`}>
                {result.status === "SETTLED" ? "✓ Payment Settled" : "✗ Transaction Failed"}
              </div>
              {result.status === "SETTLED" ? (
                <div className="space-y-1 text-sm">
                  <p className="text-slate-300">Supplier: <span className="font-semibold text-white">{result.supplier}</span></p>
                  <p className="text-slate-300">Amount: <span className="font-bold text-usdc">${result.amount_usdc.toFixed(2)} USDC</span></p>
                  <p className="text-slate-400 text-xs font-mono mt-1">Tx: {result.transaction_hash}</p>
                  <p className="text-slate-500 text-xs">Balance after: ${result.balance_after.toFixed(2)} USDC</p>
                </div>
              ) : (
                <p className="text-red-300 text-sm">{result.error}</p>
              )}
            </div>

            {/* PDF download */}
            <a
              href={`${process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"}${result.download_url}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-5 py-3 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-xl text-sm transition shrink-0"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download PDF Invoice
            </a>
          </div>

          <div className="mt-3 text-xs text-slate-500">
            Invoice ID: {result.invoice_id}
          </div>
        </div>
      )}
    </div>
  );
}
