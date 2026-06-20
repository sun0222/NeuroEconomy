"""
FastAPI backend for NeuroEconomy.
WebSocket endpoint streams real-time events to the frontend.
"""
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from orchestrator import run_orchestrator
from settlement import run_settlement, get_invoice_pdf
import config

app = FastAPI(title="NeuroEconomy", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mock_mode": config.CIRCLE_MOCK_MODE,
        "budget_cap": config.BUDGET_CAP_USDC,
        "initial_balance": config.INITIAL_BALANCE_USDC,
    }


@app.websocket("/ws/research")
async def research_ws(websocket: WebSocket):
    """
    WebSocket flow:
      1. Frontend connects
      2. Frontend sends: {"query": "..."}
      3. Backend streams events: {"type": "...", "data": {...}}
      4. Backend sends final: {"type": "complete", "data": {...}}
    """
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
        payload = json.loads(raw)
        query = payload.get("query", "").strip()

        if not query:
            await websocket.send_text(json.dumps({
                "type": "error",
                "data": {"message": "Query cannot be empty"}
            }))
            return

        async def emit(event_type: str, data: dict):
            try:
                await websocket.send_text(json.dumps({
                    "type": event_type,
                    "data": data,
                }))
            except Exception:
                pass

        result = await run_orchestrator(query, emit)

        await websocket.send_text(json.dumps({
            "type": "complete",
            "data": result,
        }))

    except asyncio.TimeoutError:
        await websocket.send_text(json.dumps({
            "type": "error",
            "data": {"message": "Timed out waiting for query"}
        }))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "data": {"message": str(e)}
            }))
        except Exception:
            pass


@app.websocket("/ws/settle")
async def settle_ws(websocket: WebSocket):
    """
    Settlement WebSocket flow:
      1. Frontend connects
      2. Frontend sends: {"product": "...", "quantity": N, "origin": "...", "destination": "..."}
      3. Backend streams steps: fetch prices → freight → landed cost → balance check → settle → invoice
      4. Backend sends: {"type": "settlement_complete", "data": {...}}
    """
    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
        payload = json.loads(raw)

        product     = payload.get("product", "").strip()
        quantity    = int(payload.get("quantity", 1000))
        origin      = payload.get("origin", "Germany").strip()
        destination = payload.get("destination", "United Kingdom").strip()

        if not product:
            await websocket.send_text(json.dumps({
                "type": "error", "data": {"message": "Product cannot be empty"}
            }))
            return

        async def emit(event_type: str, data: dict):
            try:
                await websocket.send_text(json.dumps({"type": event_type, "data": data}))
            except Exception:
                pass

        record = await run_settlement(product, quantity, origin, destination, emit)

        await websocket.send_text(json.dumps({
            "type": "settlement_complete",
            "data": {
                "invoice_id":       record.invoice_id,
                "status":           record.status,
                "amount_usdc":      record.payment_usdc,
                "transaction_hash": record.transaction_hash,
                "supplier":         record.best.supplier,
                "total_landed":     record.best.total_landed,
                "balance_before":   record.balance_before,
                "balance_after":    record.balance_after,
                "download_url":     f"/invoice/{record.invoice_id}/download",
                "error":            record.error,
            },
        }))

    except asyncio.TimeoutError:
        await websocket.send_text(json.dumps({
            "type": "error", "data": {"message": "Timeout waiting for settlement request"}
        }))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({
                "type": "error", "data": {"message": str(e)}
            }))
        except Exception:
            pass


@app.get("/invoice/{invoice_id}/download")
async def download_invoice(invoice_id: str):
    """Download generated PDF invoice."""
    pdf = get_invoice_pdf(invoice_id)
    if not pdf:
        return Response(content="Invoice not found", status_code=404)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice_id}.pdf"'},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
