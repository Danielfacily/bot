"""Backward-compat shim. Use app.engines.entry_engine instead."""
from app.engines.entry_engine import EntryEngine, EntrySignal, SETUP_NAMES

StrategyEngine = EntryEngine

__all__ = ["StrategyEngine", "EntryEngine", "EntrySignal", "SETUP_NAMES"]
