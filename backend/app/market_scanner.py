"""Backward-compat shim. Use app.engines.market_scanner instead."""
from app.engines.market_scanner import MarketScanner

__all__ = ["MarketScanner"]
