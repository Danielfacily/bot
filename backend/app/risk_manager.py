"""Backward-compat shim. Use app.engines.risk_engine instead."""
from app.engines.risk_engine import RiskEngine, RiskDecision

RiskManager = RiskEngine

__all__ = ["RiskManager", "RiskEngine", "RiskDecision"]
