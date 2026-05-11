"""Backward-compat shim. Use app.engines.execution_engine instead."""
from app.engines.execution_engine import ExecutionEngine

OrderManager = ExecutionEngine

__all__ = ["OrderManager", "ExecutionEngine"]
