"""Backward-compat shim. Use app.engines.exit_engine instead."""
from app.engines.exit_engine import ExitEngine, ExitDecision

AIExitManager = ExitEngine

__all__ = ["AIExitManager", "ExitEngine", "ExitDecision"]
