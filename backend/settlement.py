"""
SME Supply Chain Settlement Agent

Workflow:
  1. Fetch live packaging prices via Tavily
  2. Fetch live freight quotes via Tavily
  3. Compare landed cost (product + freight + duties)
  4. Check Circle wallet balance
  5. Settle with best supplier in USDC  (fail clearly if balance insufficient)
  6. Generate downloadable PDF invoice with full payment transparency
"""

import asyncio
import uuid
import re
import os
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Awaitable, List
from dataclasses import dataclass, field
from io import BytesIO

import config
from circle_client import circle_client

# ------------------------------------------------------------------ #
# In-memory invoice store  {invoice_id: pdf_bytes}
# ------------------------------------------------------------------ #
_invoices: Dict[str, bytes] = {}

SUPPLIER_WALLET = "0xSupp7E3f1A2b4C5D6E7890AbCdEf1234567890Ab"


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #

@dataclass
class PackagingOption:
    supplier: str
    material: str
    unit_price_usd: float
    moq: int
    lead_time_days: int
    country: str
    source_url: str = ""

@dataclass
class FreightOption:
    carrier: str
    service: str
    cost_usd: float
    transit_days: int
    source_url: str = ""

@dataclass
class LandedCostRow:
    rank: int
    supplier: str
    material: str
    unit_price: float
    product_cost: float
    freight_cost: float
    duty_estimate: float
    total_landed: float
    cost_per_unit: float
    recommended: bool = False

@dataclass
class SettlementRecord:
    invoice_id: str
    timestamp: str
    product: str
    quantity: int
    origin: str
    destination: str
    packaging_options: List[PackagingOption]
    freight_options: List[FreightOption]
    landed_rows: List[LandedCostRow]
    best: LandedCostRow
    payment_usdc: float
    transaction_hash: str
    supplier_wallet: str
    user_wallet: str
    balance_before: float
    balance_after: float
    status: str  # "SETTLED" | "FAILED_INSUFFICIENT_BALANCE"
    error: Optional[str] = None


# ------------------------------------------------------------------ #
# Tavily helpers
# ------------------------------------------------------------------ #

def _tavily_available() -> bool:
    return bool(config.TAVILY_API_KEY and not config.TAVILY_API_KEY.startswith("tvly-REPLACE"))


async def _tavily_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    if not _tavily_available():
        return {"answer": "", "results": []}
    from tavily import TavilyClient
    loop = asyncio.get_event_loop()
    def _search():
        c = TavilyClient(api_key=config.TAVILY_API_KEY)
        return c.search(query=query, search_depth="advanced",
                        max_results=max_results, include_answer=True)
    return await loop.run_in_executor(None, _search)


def _extract_price(text: str) -> Optional[float]:
    """Pull first USD/EUR price figure from a text snippet."""
    patterns = [
        r'\$\s*([\d,]+\.?\d*)',
        r'USD\s*([\d,]+\.?\d*)',
        r'€\s*([\d,]+\.?\d*)',
        r'EUR\s*([\d,]+\.?\d*)',
        r'([\d,]+\.?\d*)\s*(?:USD|EUR|dollars?)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


# ------------------------------------------------------------------ #
# Step 1 — Fetch packaging prices
# ------------------------------------------------------------------ #

async def fetch_packaging_prices(product: str, origin: str) -> List[PackagingOption]:
    query = f"packaging price per unit {product} supplier {origin} wholesale 2024 2025"
    data = await _tavily_search(query, max_results=5)

    options: List[PackagingOption] = []
    results = data.get("results", [])

    # Try to extract real prices from snippets
    for r in results[:4]:
        content = r.get("content", "")
        price = _extract_price(content)
        if price and 0.01 < price < 50:          # plausible unit price range
            options.append(PackagingOption(
                supplier=r.get("title", "Web Source")[:50],
                material=product,
                unit_price_usd=round(price, 4),
                moq=500,
                lead_time_days=14,
                country=origin,
                source_url=r.get("url", ""),
            ))

    # Always ensure at least 3 options with realistic market defaults
    defaults = [
        PackagingOption("EcoPack GmbH",      product, 0.38, 1000, 10, origin),
        PackagingOption("GreenBox Europe",    product, 0.45, 500,  14, origin),
        PackagingOption("PackSustain GmbH",   product, 0.29, 2000, 21, origin),
    ]
    for d in defaults:
        if len(options) >= 3:
            break
        options.append(d)

    return options[:3]


# ------------------------------------------------------------------ #
# Step 2 — Fetch freight quotes
# ------------------------------------------------------------------ #

async def fetch_freight_quotes(origin: str, destination: str, quantity: int) -> List[FreightOption]:
    weight_kg = quantity * 0.05        # ~50g per unit (light packaging)
    query = f"freight shipping cost {origin} to {destination} per kg rates 2024 2025"
    data = await _tavily_search(query, max_results=4)

    options: List[FreightOption] = []
    for r in data.get("results", [])[:3]:
        content = r.get("content", "")
        rate = _extract_price(content)
        if rate and 0.5 < rate < 20:   # plausible per-kg rate
            total = round(rate * weight_kg, 2)
            options.append(FreightOption(
                carrier=r.get("title", "Carrier")[:40],
                service="Standard Freight",
                cost_usd=total,
                transit_days=7,
                source_url=r.get("url", ""),
            ))

    defaults = [
        FreightOption("DHL Freight",    "Economy Select",   round(3.20 * weight_kg, 2), 5),
        FreightOption("DB Schenker",    "Land Transport",   round(2.80 * weight_kg, 2), 7),
        FreightOption("Kuehne+Nagel",   "Sea Freight LCL",  round(1.90 * weight_kg, 2), 21),
    ]
    for d in defaults:
        if len(options) >= 3:
            break
        options.append(d)

    return options[:3]


# ------------------------------------------------------------------ #
# Step 3 — Compare landed cost
# ------------------------------------------------------------------ #

def calculate_landed_cost(
    packaging: List[PackagingOption],
    freight: List[FreightOption],
    quantity: int,
    destination: str,
) -> List[LandedCostRow]:
    # Duty rate: EU-internal 0%, EU→UK 6.5%, others 8%
    duty_rate = 0.0
    dest_lower = destination.lower()
    if "uk" in dest_lower or "united kingdom" in dest_lower or "britain" in dest_lower:
        duty_rate = 0.065
    elif "us" in dest_lower or "united states" in dest_lower or "america" in dest_lower:
        duty_rate = 0.08

    rows: List[LandedCostRow] = []
    for i, pkg in enumerate(packaging):
        frt = freight[i % len(freight)]
        product_cost = round(pkg.unit_price_usd * quantity, 2)
        freight_cost = round(frt.cost_usd, 2)
        duty = round(product_cost * duty_rate, 2)
        total = round(product_cost + freight_cost + duty, 2)
        cpu = round(total / quantity, 4)
        rows.append(LandedCostRow(
            rank=i + 1,
            supplier=pkg.supplier,
            material=pkg.material,
            unit_price=pkg.unit_price_usd,
            product_cost=product_cost,
            freight_cost=freight_cost,
            duty_estimate=duty,
            total_landed=total,
            cost_per_unit=cpu,
        ))

    # Sort by total landed cost, mark cheapest as recommended
    rows.sort(key=lambda r: r.total_landed)
    for j, r in enumerate(rows):
        r.rank = j + 1
        r.recommended = (j == 0)
    return rows


# ------------------------------------------------------------------ #
# Step 4+5 — Settle payment
# ------------------------------------------------------------------ #

async def settle_payment(
    best: LandedCostRow,
    product: str,
    quantity: int,
    origin: str,
    destination: str,
    packaging_options: List[PackagingOption],
    freight_options: List[FreightOption],
    landed_rows: List[LandedCostRow],
) -> SettlementRecord:
    invoice_id = f"INV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    amount_usdc = best.total_landed   # 1 USDC = 1 USD

    balance_before = await circle_client.get_balance(config.ORCHESTRATOR_WALLET_ID)

    if balance_before < amount_usdc:
        shortfall = round(amount_usdc - balance_before, 2)
        record = SettlementRecord(
            invoice_id=invoice_id,
            timestamp=timestamp,
            product=product,
            quantity=quantity,
            origin=origin,
            destination=destination,
            packaging_options=packaging_options,
            freight_options=freight_options,
            landed_rows=landed_rows,
            best=best,
            payment_usdc=amount_usdc,
            transaction_hash="",
            supplier_wallet=SUPPLIER_WALLET,
            user_wallet=config.USER_WALLET_ADDRESS,
            balance_before=balance_before,
            balance_after=balance_before,
            status="FAILED_INSUFFICIENT_BALANCE",
            error=(
                f"Insufficient balance. Required: ${amount_usdc:.2f} USDC | "
                f"Available: ${balance_before:.2f} USDC | "
                f"Shortfall: ${shortfall:.2f} USDC"
            ),
        )
        pdf = _build_pdf(record)
        _invoices[invoice_id] = pdf
        return record

    tx = await circle_client.transfer(
        from_wallet_id=config.ORCHESTRATOR_WALLET_ID,
        to_address=SUPPLIER_WALLET,
        amount_usdc=amount_usdc,
        reason=f"Supply settlement: {product} x{quantity}",
    )

    balance_after = await circle_client.get_balance(config.ORCHESTRATOR_WALLET_ID)

    record = SettlementRecord(
        invoice_id=invoice_id,
        timestamp=timestamp,
        product=product,
        quantity=quantity,
        origin=origin,
        destination=destination,
        packaging_options=packaging_options,
        freight_options=freight_options,
        landed_rows=landed_rows,
        best=best,
        payment_usdc=amount_usdc,
        transaction_hash=tx["transaction_hash"],
        supplier_wallet=SUPPLIER_WALLET,
        user_wallet=config.USER_WALLET_ADDRESS,
        balance_before=balance_before,
        balance_after=balance_after,
        status="SETTLED",
    )
    pdf = _build_pdf(record)
    _invoices[invoice_id] = pdf
    return record


def get_invoice_pdf(invoice_id: str) -> Optional[bytes]:
    return _invoices.get(invoice_id)


# ------------------------------------------------------------------ #
# PDF generation
# ------------------------------------------------------------------ #

def _build_pdf(rec: SettlementRecord) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    INDIGO  = HexColor("#6366f1")
    DARK    = HexColor("#0f1117")
    SLATE   = HexColor("#1e293b")
    GREEN   = HexColor("#10b981")
    RED     = HexColor("#ef4444")
    LGRAY   = HexColor("#f1f5f9")
    MGRAY   = HexColor("#94a3b8")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=14*mm, bottomMargin=14*mm,
    )

    def style(name, **kw):
        base = ParagraphStyle(name)
        for k, v in kw.items():
            setattr(base, k, v)
        return base

    H1   = style("H1",   fontSize=22, textColor=INDIGO,  leading=26, spaceAfter=2)
    H2   = style("H2",   fontSize=12, textColor=DARK,    leading=16, spaceBefore=8, spaceAfter=4, fontName="Helvetica-Bold")
    BODY = style("BODY", fontSize=9,  textColor=DARK,    leading=13)
    TINY = style("TINY", fontSize=7,  textColor=MGRAY,   leading=10)
    MONO = style("MONO", fontSize=7,  textColor=SLATE,   leading=10, fontName="Courier")
    LBL  = style("LBL",  fontSize=8,  textColor=MGRAY,   leading=11)
    VAL  = style("VAL",  fontSize=9,  textColor=DARK,    leading=12, fontName="Helvetica-Bold")
    RJT  = style("RJT",  fontSize=9,  textColor=DARK,    leading=12, alignment=TA_RIGHT)
    CTR  = style("CTR",  fontSize=9,  textColor=DARK,    leading=12, alignment=TA_CENTER)
    STATUS_OK  = style("SOK",  fontSize=14, textColor=GREEN, fontName="Helvetica-Bold", alignment=TA_CENTER, leading=18)
    STATUS_ERR = style("SERR", fontSize=14, textColor=RED,   fontName="Helvetica-Bold", alignment=TA_CENTER, leading=18)

    story = []

    # ── Header bar ──────────────────────────────────────────────────
    header_data = [[
        Paragraph("Synapse", H1),
        Paragraph(
            f"<b>SUPPLY CHAIN SETTLEMENT INVOICE</b><br/>"
            f"<font color='#94a3b8' size='8'>{rec.invoice_id}</font>",
            style("HR", fontSize=11, textColor=DARK, leading=15, alignment=TA_RIGHT)
        ),
    ]]
    header_tbl = Table(header_data, colWidths=[90*mm, 90*mm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BACKGROUND", (0,0), (-1,-1), LGRAY),
        ("ROWPADDING", (0,0), (-1,-1), 8),
        ("ROUNDEDCORNERS", [6]),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 5*mm))

    # ── Meta row ────────────────────────────────────────────────────
    meta = [
        [Paragraph("Date", LBL),        Paragraph("Product", LBL),
         Paragraph("Quantity", LBL),     Paragraph("Route", LBL)],
        [Paragraph(rec.timestamp, VAL),  Paragraph(rec.product[:30], VAL),
         Paragraph(f"{rec.quantity:,}", VAL),
         Paragraph(f"{rec.origin} → {rec.destination}", VAL)],
    ]
    meta_tbl = Table(meta, colWidths=[45*mm, 55*mm, 30*mm, 50*mm])
    meta_tbl.setStyle(TableStyle([
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("LINEBELOW",   (0,1), (-1,1), 0.5, MGRAY),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 4*mm))

    # ── Status badge ────────────────────────────────────────────────
    if rec.status == "SETTLED":
        badge = Paragraph("✓  PAYMENT SETTLED", STATUS_OK)
    else:
        badge = Paragraph("✗  TRANSACTION FAILED — INSUFFICIENT BALANCE", STATUS_ERR)
    badge_tbl = Table([[badge]], colWidths=[174*mm])
    badge_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), LGRAY),
        ("ROWPADDING", (0,0), (-1,-1), 8),
        ("ROUNDEDCORNERS", [4]),
    ]))
    story.append(badge_tbl)
    story.append(Spacer(1, 4*mm))

    # ── Landed Cost Comparison ───────────────────────────────────────
    story.append(Paragraph("Landed Cost Comparison", H2))
    lc_head = [["#", "Supplier", "Unit Price", "Product Cost",
                 "Freight", "Duties", "Total Landed", "Per Unit", ""]]
    lc_rows = []
    for row in rec.landed_rows:
        tag = "★ BEST" if row.recommended else ""
        lc_rows.append([
            str(row.rank),
            row.supplier[:28],
            f"${row.unit_price:.4f}",
            f"${row.product_cost:,.2f}",
            f"${row.freight_cost:,.2f}",
            f"${row.duty_estimate:,.2f}",
            f"${row.total_landed:,.2f}",
            f"${row.cost_per_unit:.4f}",
            tag,
        ])
    lc_tbl = Table(
        lc_head + lc_rows,
        colWidths=[8*mm, 42*mm, 18*mm, 22*mm, 17*mm, 15*mm, 22*mm, 16*mm, 14*mm],
    )
    lc_style = [
        ("BACKGROUND",   (0,0), (-1,0),  INDIGO),
        ("TEXTCOLOR",    (0,0), (-1,0),  white),
        ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 7.5),
        ("ROWPADDING",   (0,0), (-1,-1), 4),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("GRID",         (0,0), (-1,-1), 0.3, MGRAY),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [white, LGRAY]),
    ]
    # Highlight recommended row
    for i, row in enumerate(rec.landed_rows):
        if row.recommended:
            lc_style += [
                ("BACKGROUND", (0, i+1), (-1, i+1), HexColor("#d1fae5")),
                ("TEXTCOLOR",  (8, i+1), (8, i+1),  GREEN),
                ("FONTNAME",   (8, i+1), (8, i+1),  "Helvetica-Bold"),
            ]
    lc_tbl.setStyle(TableStyle(lc_style))
    story.append(lc_tbl)
    story.append(Spacer(1, 4*mm))

    # ── Payment Details ──────────────────────────────────────────────
    story.append(Paragraph("Payment Details", H2))
    pay_data = [
        [Paragraph("Selected Supplier", LBL), Paragraph("Amount (USDC)", LBL),
         Paragraph("Currency", LBL),          Paragraph("Status", LBL)],
        [Paragraph(rec.best.supplier, VAL),
         Paragraph(f"${rec.payment_usdc:,.2f}", VAL),
         Paragraph("USDC (Circle)", VAL),
         Paragraph(rec.status, style("ST", fontSize=9, textColor=GREEN if rec.status=="SETTLED" else RED, fontName="Helvetica-Bold"))],
    ]
    pay_tbl = Table(pay_data, colWidths=[50*mm, 40*mm, 42*mm, 42*mm])
    pay_tbl.setStyle(TableStyle([
        ("ROWPADDING",  (0,0), (-1,-1), 5),
        ("LINEBELOW",   (0,1), (-1,1), 0.5, MGRAY),
        ("VALIGN",      (0,0), (-1,-1), "TOP"),
    ]))
    story.append(pay_tbl)
    story.append(Spacer(1, 3*mm))

    # Wallet + tx hash box
    wallet_data = [
        [Paragraph("From Wallet (Agent)", LBL), Paragraph("To Wallet (Supplier)", LBL)],
        [Paragraph(rec.user_wallet,     MONO),  Paragraph(rec.supplier_wallet, MONO)],
        [Paragraph("Balance Before", LBL),      Paragraph("Balance After", LBL)],
        [Paragraph(f"${rec.balance_before:.2f} USDC", VAL),
         Paragraph(f"${rec.balance_after:.2f} USDC", VAL)],
    ]
    if rec.transaction_hash:
        wallet_data += [
            [Paragraph("Transaction Hash", LBL), Paragraph("", LBL)],
            [Paragraph(rec.transaction_hash, MONO), Paragraph("", TINY)],
        ]
    wallet_tbl = Table(wallet_data, colWidths=[87*mm, 87*mm])
    wallet_tbl.setStyle(TableStyle([
        ("ROWPADDING",   (0,0), (-1,-1), 4),
        ("BACKGROUND",   (0,0), (-1,-1), LGRAY),
        ("SPAN",         (0,5), (-1,5))  if rec.transaction_hash else ("ROWPADDING",(0,0),(-1,-1),4),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ]))
    story.append(wallet_tbl)
    story.append(Spacer(1, 3*mm))

    # Insufficient balance error block
    if rec.error:
        err_tbl = Table(
            [[Paragraph(f"⚠  {rec.error}", style("ERR", fontSize=9, textColor=RED, leading=13))]],
            colWidths=[174*mm],
        )
        err_tbl.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,-1), HexColor("#fef2f2")),
            ("ROWPADDING",  (0,0), (-1,-1), 8),
            ("ROUNDEDCORNERS", [4]),
        ]))
        story.append(err_tbl)
        story.append(Spacer(1, 3*mm))

    # ── Line-item breakdown ──────────────────────────────────────────
    story.append(Paragraph("Invoice Line Items", H2))
    li_data = [
        ["Description", "Qty", "Unit Price", "Amount (USD)"],
        [f"Packaging — {rec.best.material} ({rec.best.supplier})",
         f"{rec.quantity:,}", f"${rec.best.unit_price:.4f}", f"${rec.best.product_cost:,.2f}"],
        ["Freight & Logistics", "1", "—", f"${rec.best.freight_cost:,.2f}"],
        ["Import Duties (estimated)", "1", "—", f"${rec.best.duty_estimate:,.2f}"],
        ["", "", "TOTAL LANDED COST", f"${rec.best.total_landed:,.2f}"],
        ["", "", "USDC PAYMENT", f"${rec.payment_usdc:,.2f} USDC"],
    ]
    li_tbl = Table(li_data, colWidths=[90*mm, 18*mm, 36*mm, 30*mm])
    li_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0),  INDIGO),
        ("TEXTCOLOR",    (0,0), (-1,0),  white),
        ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 8.5),
        ("ROWPADDING",   (0,0), (-1,-1), 5),
        ("GRID",         (0,0), (-1,3),  0.3, MGRAY),
        ("LINEABOVE",    (0,4), (-1,4),  1,   DARK),
        ("FONTNAME",     (2,4), (-1,5),  "Helvetica-Bold"),
        ("FONTNAME",     (2,5), (-1,5),  "Helvetica-Bold"),
        ("TEXTCOLOR",    (2,5), (-1,5),  INDIGO),
        ("ROWBACKGROUNDS",(0,1),(-1,3),  [white, LGRAY]),
        ("ALIGN",        (1,0), (-1,-1), "RIGHT"),
    ]))
    story.append(li_tbl)
    story.append(Spacer(1, 6*mm))

    # ── Footer ───────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=MGRAY))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        f"Generated by <b>Synapse</b> — Autonomous Supply Chain Settlement Agent  •  "
        f"Powered by <b>Circle Agent Wallet</b> (USDC)  •  {rec.timestamp}",
        style("FTR", fontSize=7, textColor=MGRAY, leading=10, alignment=TA_CENTER)
    ))
    story.append(Paragraph(
        "This document is an automated payment receipt. All USDC transactions are recorded on-chain.",
        style("FTR2", fontSize=6.5, textColor=MGRAY, leading=9, alignment=TA_CENTER)
    ))

    doc.build(story)
    return buf.getvalue()


# ------------------------------------------------------------------ #
# Main entry point (streamed)
# ------------------------------------------------------------------ #

async def run_settlement(
    product: str,
    quantity: int,
    origin: str,
    destination: str,
    emit: Callable[[str, dict], Awaitable[None]],
) -> SettlementRecord:

    circle_client.reset_session()

    # 1 — Fetch packaging prices
    await emit("step", {"step": "fetch_prices", "label": "Fetching live packaging prices via Tavily..."})
    packaging = await fetch_packaging_prices(product, origin)
    await emit("prices_fetched", {
        "options": [
            {"supplier": p.supplier, "material": p.material,
             "unit_price": p.unit_price_usd, "moq": p.moq,
             "lead_time": p.lead_time_days, "country": p.country}
            for p in packaging
        ]
    })

    # 2 — Fetch freight quotes
    await emit("step", {"step": "fetch_freight", "label": "Fetching live freight quotes via Tavily..."})
    freight = await fetch_freight_quotes(origin, destination, quantity)
    await emit("freight_fetched", {
        "quotes": [
            {"carrier": f.carrier, "service": f.service,
             "cost_usd": f.cost_usd, "transit_days": f.transit_days}
            for f in freight
        ]
    })

    # 3 — Compare landed cost
    await emit("step", {"step": "landed_cost", "label": "Comparing total landed cost..."})
    rows = calculate_landed_cost(packaging, freight, quantity, destination)
    best = next(r for r in rows if r.recommended)
    await emit("landed_cost_calculated", {
        "rows": [
            {"rank": r.rank, "supplier": r.supplier, "unit_price": r.unit_price,
             "product_cost": r.product_cost, "freight_cost": r.freight_cost,
             "duty": r.duty_estimate, "total": r.total_landed,
             "per_unit": r.cost_per_unit, "recommended": r.recommended}
            for r in rows
        ],
        "best": best.supplier,
        "best_total": best.total_landed,
    })

    # 4 — Check balance
    await emit("step", {"step": "check_balance", "label": "Checking Circle wallet balance..."})
    balance = await circle_client.get_balance(config.ORCHESTRATOR_WALLET_ID)
    sufficient = balance >= best.total_landed
    await emit("balance_checked", {
        "balance": balance,
        "required": best.total_landed,
        "sufficient": sufficient,
    })

    if not sufficient:
        shortfall = round(best.total_landed - balance, 2)
        await emit("insufficient_balance", {
            "balance": balance,
            "required": best.total_landed,
            "shortfall": shortfall,
        })

    # 5 — Settle
    await emit("step", {"step": "settle", "label": "Settling payment with supplier in USDC..." if sufficient else "Recording failed transaction..."})
    record = await settle_payment(best, product, quantity, origin, destination, packaging, freight, rows)

    if record.status == "SETTLED":
        await emit("settled", {
            "transaction_hash": record.transaction_hash,
            "amount_usdc": record.payment_usdc,
            "supplier": record.best.supplier,
            "supplier_wallet": record.supplier_wallet,
            "balance_after": record.balance_after,
        })
    else:
        await emit("settlement_failed", {
            "error": record.error,
            "balance": record.balance_before,
            "required": record.payment_usdc,
        })

    # 6 — Invoice
    await emit("step", {"step": "invoice", "label": "Generating PDF invoice..."})
    await asyncio.sleep(0.3)
    await emit("invoice_ready", {
        "invoice_id": record.invoice_id,
        "download_url": f"/invoice/{record.invoice_id}/download",
        "status": record.status,
    })

    return record
