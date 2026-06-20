"""
NeuroEconomy orchestrator — Claude Agent SDK powered agentic loop.

Claude uses tool_use to:
  1. Check Circle wallet balance
  2. Discover agents on Circle Marketplace
  3. Score relevance of each agent before spending
  4. Pay agents via Circle transfer and collect research data
  5. Refund unused budget to user
  6. Synthesize final intelligence brief

Set DEMO_MODE=true in .env to run without Anthropic API credits (full UI
flow with scripted tool calls — great for testing and demos).
"""
import asyncio
import json
from typing import Callable, Awaitable
import anthropic
import config
from circle_client import circle_client
from specialist_agents import AGENT_REGISTRY, query_agent, clear_session_data
from models import OrchestratorState, PaymentRecord, AgentEvaluation

_claude = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are NeuroEconomy — an autonomous intelligence orchestrator that holds a Circle USDC wallet.

Your job: research any topic by hiring specialist agents, paying them in USDC, and delivering a comprehensive intelligence brief.

STRICT PROTOCOL:
1. Call check_wallet_balance FIRST — always.
2. Call discover_available_agents to see what you can hire.
3. For EACH agent: call evaluate_agent_relevance with a score 0.0–1.0 and whether you will hire it.
   - Only hire agents with score ≥ 0.55. Skip the rest and explain why.
4. For agents you will hire: call pay_and_query_agent. Never use agent data without paying first.
5. Stay within the budget cap. If a payment would exceed the cap, skip that agent.
6. After all research is done: call refund_unused_budget with the exact remaining amount.
7. Finally: call synthesize_final_brief with all collected findings.

Be transparent and financially accountable at every step."""

TOOLS = [
    {
        "name": "check_wallet_balance",
        "description": "Check the current USDC balance of the orchestrator Circle wallet",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "discover_available_agents",
        "description": "List all specialist agents available for hire on Circle Agent Marketplace, with pricing",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "evaluate_agent_relevance",
        "description": "Evaluate how relevant a specialist agent is before deciding to hire it",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "relevance_score": {
                    "type": "number",
                    "description": "0.0 (irrelevant) to 1.0 (perfect fit)",
                },
                "reasoning": {"type": "string", "description": "Why hire or skip this agent"},
                "will_hire": {"type": "boolean"},
            },
            "required": ["agent_name", "relevance_score", "reasoning", "will_hire"],
        },
    },
    {
        "name": "pay_and_query_agent",
        "description": "Pay a specialist agent in USDC via Circle wallet transfer and receive their research output",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string"},
                "query": {
                    "type": "string",
                    "description": "Specific research question tailored to this agent's specialty",
                },
            },
            "required": ["agent_name", "query"],
        },
    },
    {
        "name": "refund_unused_budget",
        "description": "Send remaining USDC budget back to the user's Circle wallet",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount_usdc": {"type": "number"},
                "message": {"type": "string"},
            },
            "required": ["amount_usdc", "message"],
        },
    },
    {
        "name": "synthesize_final_brief",
        "description": "Compile all purchased research into a final intelligence brief",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "executive_summary": {"type": "string"},
                "key_findings": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "array", "items": {"type": "string"}},
                "data_sources": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "executive_summary", "key_findings", "recommendations", "data_sources"],
        },
    },
]


# ------------------------------------------------------------------ #
# Tool handler
# ------------------------------------------------------------------ #

async def _handle_tool(
    name: str,
    inputs: dict,
    state: OrchestratorState,
    emit: Callable,
) -> dict:

    if name == "check_wallet_balance":
        balance = await circle_client.get_balance(config.ORCHESTRATOR_WALLET_ID)
        state.balance = balance
        await emit("balance_checked", {
            "balance": balance,
            "budget_cap": state.budget_cap,
            "wallet_address": config.ORCHESTRATOR_ADDRESS,
        })
        return {
            "balance_usdc": balance,
            "budget_cap_usdc": state.budget_cap,
            "wallet_id": config.ORCHESTRATOR_WALLET_ID,
            "wallet_address": config.ORCHESTRATOR_ADDRESS,
        }

    if name == "discover_available_agents":
        await emit("agents_discovered", {"agents": AGENT_REGISTRY})
        return {"available_agents": AGENT_REGISTRY, "count": len(AGENT_REGISTRY)}

    if name == "evaluate_agent_relevance":
        evaluation = AgentEvaluation(
            agent_name=inputs["agent_name"],
            relevance_score=inputs["relevance_score"],
            reasoning=inputs["reasoning"],
            will_hire=inputs["will_hire"],
        )
        state.evaluations.append(evaluation)
        agent_info = AGENT_REGISTRY.get(inputs["agent_name"], {})
        await emit("agent_evaluated", {
            "agent_name": inputs["agent_name"],
            "score": inputs["relevance_score"],
            "reasoning": inputs["reasoning"],
            "will_hire": inputs["will_hire"],
            "price_usdc": agent_info.get("price_usdc", 0),
        })
        return {
            "recorded": True,
            "agent": inputs["agent_name"],
            "score": inputs["relevance_score"],
            "will_hire": inputs["will_hire"],
        }

    if name == "pay_and_query_agent":
        agent_name = inputs["agent_name"]
        query = inputs["query"]

        if agent_name not in AGENT_REGISTRY:
            return {"error": f"Agent '{agent_name}' not found in marketplace"}

        agent = AGENT_REGISTRY[agent_name]
        cost = agent["price_usdc"]

        # Budget guard
        if state.total_spent + cost > state.budget_cap:
            await emit("budget_exceeded", {
                "agent_name": agent_name,
                "cost": cost,
                "remaining_budget": state.budget_remaining,
            })
            return {
                "error": "Budget cap would be exceeded — agent skipped",
                "cost": cost,
                "remaining_budget": state.budget_remaining,
            }

        # Execute Circle payment
        await emit("payment_initiating", {
            "agent_name": agent_name,
            "amount_usdc": cost,
            "to_address": agent["wallet_address"],
        })

        tx = await circle_client.transfer(
            from_wallet_id=config.ORCHESTRATOR_WALLET_ID,
            to_address=agent["wallet_address"],
            amount_usdc=cost,
            reason=f"Research service: {agent_name}",
        )

        state.total_spent = round(state.total_spent + cost, 4)
        state.balance = round(state.balance - cost, 4)

        payment = PaymentRecord(
            agent_name=agent_name,
            amount_usdc=cost,
            transaction_hash=tx["transaction_hash"],
            to_address=agent["wallet_address"],
            query=query,
        )
        state.payments.append(payment)

        await emit("payment_confirmed", {
            "agent_name": agent_name,
            "amount_usdc": cost,
            "transaction_hash": tx["transaction_hash"],
            "to_address": agent["wallet_address"],
            "total_spent": state.total_spent,
            "remaining_balance": state.balance,
            "budget_remaining": state.budget_remaining,
        })

        # Query the specialist agent
        await emit("agent_querying", {"agent_name": agent_name, "query": query})
        research = await query_agent(agent_name, query)
        state.collected_data[agent_name] = research

        await emit("agent_responded", {
            "agent_name": agent_name,
            "findings_count": len(research.get("findings", [])),
            "confidence": research.get("confidence", 0),
        })

        return {
            "agent": agent_name,
            "paid_usdc": cost,
            "transaction_hash": tx["transaction_hash"],
            "research_data": research,
        }

    if name == "refund_unused_budget":
        amount = round(inputs["amount_usdc"], 4)
        message = inputs.get("message", "Unused budget returned")

        if amount > 0.001:
            tx = await circle_client.transfer(
                from_wallet_id=config.ORCHESTRATOR_WALLET_ID,
                to_address=config.USER_WALLET_ADDRESS,
                amount_usdc=amount,
                reason="Budget refund to user",
            )
            state.refunded = amount
            await emit("refund_sent", {
                "amount_usdc": amount,
                "transaction_hash": tx["transaction_hash"],
                "to_address": config.USER_WALLET_ADDRESS,
                "message": message,
            })
            return {"refunded_usdc": amount, "transaction_hash": tx["transaction_hash"]}

        return {"refunded_usdc": 0, "message": "Amount too small to refund"}

    if name == "synthesize_final_brief":
        state.final_brief = inputs
        state.brief_ready = True
        await emit("brief_ready", {"title": inputs.get("title", "Intelligence Brief")})
        return {"status": "Brief synthesized successfully"}

    return {"error": f"Unknown tool: {name}"}


# ------------------------------------------------------------------ #
# Main orchestrator loop
# ------------------------------------------------------------------ #

async def _run_demo_orchestrator(query: str, emit: Callable[[str, dict], Awaitable[None]]) -> dict:
    """
    Scripted orchestrator that runs the full workflow without calling the
    Anthropic API. Identical Circle wallet calls, identical event stream.
    Use DEMO_MODE=true in .env to activate.
    """
    state = OrchestratorState(
        query=query,
        balance=config.INITIAL_BALANCE_USDC,
        budget_cap=config.BUDGET_CAP_USDC,
    )

    circle_client.reset_session()
    clear_session_data()
    await emit("started", {"query": query, "initial_balance": state.balance, "budget_cap": state.budget_cap})
    await asyncio.sleep(0.5)

    # Step 1 — check wallet balance
    result = await _handle_tool("check_wallet_balance", {}, state, emit)
    await asyncio.sleep(0.8)

    # Step 2 — discover agents
    result = await _handle_tool("discover_available_agents", {}, state, emit)
    await asyncio.sleep(0.6)

    # Step 3 — evaluate each agent
    evaluations_plan = [
        ("NewsAggAgent",     0.88, "Recent news is critical to understand market sentiment and identify active players.", True),
        ("WebIntelAgent",    0.82, "Web intelligence will surface specific companies matching the research profile.", True),
        ("DataAnalysisAgent",0.91, "Market sizing and financial metrics are core to an acquisition brief.", True),
        ("PatentSearchAgent",0.65, "Patent landscape adds useful IP intelligence for acquisition due diligence.", True),
        ("SynthesisAgent",   0.95, "Synthesis is required to compile all findings into a decision-ready brief.", True),
    ]

    for agent_name, score, reasoning, will_hire in evaluations_plan:
        await _handle_tool("evaluate_agent_relevance", {
            "agent_name": agent_name,
            "relevance_score": score,
            "reasoning": reasoning,
            "will_hire": will_hire,
        }, state, emit)
        await asyncio.sleep(0.4)

    # Step 4 — pay and query each hired agent
    agent_queries = {
        "NewsAggAgent":     query,
        "WebIntelAgent":    query,
        "DataAnalysisAgent":query,
        "PatentSearchAgent":query,
        "SynthesisAgent":   query,
    }

    for agent_name, agent_query in agent_queries.items():
        await _handle_tool("pay_and_query_agent", {
            "agent_name": agent_name,
            "query": agent_query,
        }, state, emit)
        await asyncio.sleep(0.3)

    # Step 5 — refund unused budget (use actual wallet balance, not just budget math)
    remaining = round(state.balance, 4)
    if remaining > 0:
        await _handle_tool("refund_unused_budget", {
            "amount_usdc": remaining,
            "message": f"Research complete. ${remaining:.2f} USDC unused budget returned to user.",
        }, state, emit)
        await asyncio.sleep(0.4)

    # Step 6 — build final brief from real SynthesisAgent output
    synth = state.collected_data.get("SynthesisAgent", {})
    all_sources = [
        state.collected_data.get(a, {}).get("source", a)
        for a in ["NewsAggAgent", "WebIntelAgent", "DataAnalysisAgent", "PatentSearchAgent"]
        if a in state.collected_data
    ]

    brief = {
        "title": f"Intelligence Brief: {query[:70]}{'...' if len(query) > 70 else ''}",
        "executive_summary": synth.get(
            "executive_summary",
            f"Research completed across {len(state.payments)} paid sources "
            f"totaling ${state.total_spent:.2f} USDC."
        ),
        "key_findings": synth.get("findings", []),
        "recommendations": synth.get("recommendations", []),
        "data_sources": all_sources,
    }

    await _handle_tool("synthesize_final_brief", brief, state, emit)
    await asyncio.sleep(0.3)

    await emit("finished", {
        "total_spent": state.total_spent,
        "refunded": state.refunded,
        "payments_count": len(state.payments),
    })

    return {
        "brief": state.final_brief,
        "payments": [p.model_dump() for p in state.payments],
        "evaluations": [e.model_dump() for e in state.evaluations],
        "total_spent": state.total_spent,
        "refunded": state.refunded,
        "initial_balance": config.INITIAL_BALANCE_USDC,
        "budget_cap": config.BUDGET_CAP_USDC,
    }


async def run_orchestrator(query: str, emit: Callable[[str, dict], Awaitable[None]]) -> dict:
    import os
    if os.getenv("DEMO_MODE", "false").lower() == "true":
        return await _run_demo_orchestrator(query, emit)

    circle_client.reset_session()
    state = OrchestratorState(
        query=query,
        balance=config.INITIAL_BALANCE_USDC,
        budget_cap=config.BUDGET_CAP_USDC,
    )

    await emit("started", {
        "query": query,
        "initial_balance": state.balance,
        "budget_cap": state.budget_cap,
    })

    messages = [
        {
            "role": "user",
            "content": (
                f"Research task: {query}\n"
                f"Budget cap: ${config.BUDGET_CAP_USDC} USDC\n"
                f"Please conduct comprehensive research, pay for relevant data sources, "
                f"refund unused budget, and deliver a decision-ready intelligence brief."
            ),
        }
    ]

    max_iterations = 30
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        response = _claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            result = await _handle_tool(block.name, block.input, state, emit)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })

        messages.append({"role": "user", "content": tool_results})

        if state.brief_ready:
            break

    await emit("finished", {
        "total_spent": state.total_spent,
        "refunded": state.refunded,
        "payments_count": len(state.payments),
    })

    return {
        "brief": state.final_brief,
        "payments": [p.model_dump() for p in state.payments],
        "evaluations": [e.model_dump() for e in state.evaluations],
        "total_spent": state.total_spent,
        "refunded": state.refunded,
        "initial_balance": config.INITIAL_BALANCE_USDC,
        "budget_cap": config.BUDGET_CAP_USDC,
    }
