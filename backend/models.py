from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class PaymentRecord(BaseModel):
    agent_name: str
    amount_usdc: float
    transaction_hash: str
    to_address: str
    query: str
    status: str = "CONFIRMED"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class AgentEvaluation(BaseModel):
    agent_name: str
    relevance_score: float
    reasoning: str
    will_hire: bool


class FinalBrief(BaseModel):
    title: str
    executive_summary: str
    key_findings: List[str]
    recommendations: List[str]
    data_sources: List[str] = []


class ResearchResult(BaseModel):
    brief: Optional[Dict[str, Any]]
    payments: List[Dict[str, Any]]
    evaluations: List[Dict[str, Any]]
    total_spent: float
    refunded: float
    initial_balance: float
    budget_cap: float


class OrchestratorState:
    def __init__(self, query: str, balance: float, budget_cap: float):
        self.query = query
        self.balance = balance
        self.budget_cap = budget_cap
        self.total_spent: float = 0.0
        self.refunded: float = 0.0
        self.payments: List[PaymentRecord] = []
        self.evaluations: List[AgentEvaluation] = []
        self.collected_data: Dict[str, Any] = {}
        self.final_brief: Optional[Dict] = None
        self.brief_ready: bool = False

    @property
    def budget_remaining(self) -> float:
        return round(self.budget_cap - self.total_spent, 4)
