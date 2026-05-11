"""Backward-compat shim. Use app.engines.ai_engine instead."""
from app.engines.ai_engine import AIEngine, FEATURES

SignalClassifier = AIEngine

__all__ = ["SignalClassifier", "AIEngine", "FEATURES"]
