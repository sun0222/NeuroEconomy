"""
Circle Agent Wallet client.
Runs in mock mode by default (CIRCLE_MOCK_MODE=true) so the app works
immediately without Circle credentials. Set CIRCLE_MOCK_MODE=false and
provide CIRCLE_API_KEY to use the real Circle sandbox API.
"""
import httpx
import uuid
import hashlib
import time
from typing import Dict
import config


class CircleClient:
    SANDBOX_URL = "https://api-sandbox.circle.com/v1/w3s"

    def __init__(self):
        # In-memory wallet store for mock mode
        self._balances: Dict[str, float] = {
            config.ORCHESTRATOR_WALLET_ID: config.INITIAL_BALANCE_USDC
        }
        self._tx_counter = 0

    def reset_session(self) -> None:
        """Reset orchestrator wallet to initial balance for a new research session."""
        self._balances[config.ORCHESTRATOR_WALLET_ID] = config.INITIAL_BALANCE_USDC

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _fake_tx_hash(self) -> str:
        self._tx_counter += 1
        seed = f"{time.time()}{self._tx_counter}{uuid.uuid4()}"
        return "0x" + hashlib.sha256(seed.encode()).hexdigest()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {config.CIRCLE_API_KEY}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def get_balance(self, wallet_id: str) -> float:
        if config.CIRCLE_MOCK_MODE:
            return round(self._balances.get(wallet_id, 0.0), 4)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.SANDBOX_URL}/wallets/{wallet_id}/balances",
                headers=self._headers(),
            )
            resp.raise_for_status()
            token_balances = resp.json().get("data", {}).get("tokenBalances", [])
            usdc = next(
                (b for b in token_balances if b.get("token", {}).get("symbol") == "USDC"),
                None,
            )
            return float(usdc["amount"]) if usdc else 0.0

    async def transfer(
        self,
        from_wallet_id: str,
        to_address: str,
        amount_usdc: float,
        reason: str = "",
    ) -> dict:
        if config.CIRCLE_MOCK_MODE:
            current = self._balances.get(from_wallet_id, 0.0)
            if current < amount_usdc:
                raise ValueError(f"Insufficient balance: {current:.2f} USDC < {amount_usdc:.2f} USDC")
            self._balances[from_wallet_id] = round(current - amount_usdc, 4)
            return {
                "transaction_hash": self._fake_tx_hash(),
                "amount_usdc": amount_usdc,
                "from_wallet_id": from_wallet_id,
                "to_address": to_address,
                "status": "CONFIRMED",
                "reason": reason,
            }

        # Real Circle sandbox transfer
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.SANDBOX_URL}/developer/transactions/transfer",
                headers=self._headers(),
                json={
                    "idempotencyKey": str(uuid.uuid4()),
                    "walletId": from_wallet_id,
                    "tokenId": "USDC",
                    "destinationAddress": to_address,
                    "amounts": [str(amount_usdc)],
                    "feeLevel": "MEDIUM",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {
                "transaction_hash": data.get("txHash", "pending"),
                "amount_usdc": amount_usdc,
                "from_wallet_id": from_wallet_id,
                "to_address": to_address,
                "status": data.get("state", "INITIATED"),
                "reason": reason,
            }

    async def create_wallet(self, name: str) -> dict:
        """Create a new agent wallet (mock or real)."""
        if config.CIRCLE_MOCK_MODE:
            wallet_id = f"mock_{name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}"
            address = "0x" + hashlib.sha256(wallet_id.encode()).hexdigest()[:40]
            self._balances[wallet_id] = 0.0
            return {"wallet_id": wallet_id, "address": address, "name": name}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.SANDBOX_URL}/developer/wallets",
                headers=self._headers(),
                json={
                    "idempotencyKey": str(uuid.uuid4()),
                    "count": 1,
                    "blockchains": ["MATIC-AMOY"],
                },
            )
            resp.raise_for_status()
            wallets = resp.json().get("data", {}).get("wallets", [{}])
            w = wallets[0]
            return {
                "wallet_id": w.get("id"),
                "address": w.get("address"),
                "name": name,
            }


circle_client = CircleClient()
