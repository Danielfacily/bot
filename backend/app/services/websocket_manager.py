"""WebSocket Manager — broadcasting de eventos para o dashboard."""
from fastapi import WebSocket
import json
from datetime import datetime


class WebSocketManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.connections = [c for c in self.connections if c != ws]

    async def broadcast(self, event_type: str, data: dict) -> None:
        payload = json.dumps({
            "type": event_type,
            "data": data,
            "ts": datetime.utcnow().isoformat(),
        }, default=str)
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_log(self, level: str, source: str, message: str, details: dict | None = None) -> None:
        await self.broadcast("log", {
            "level": level, "source": source, "message": message, "details": details or {}
        })

    async def broadcast_signal(self, signal_data: dict) -> None:
        await self.broadcast("signal", signal_data)

    async def broadcast_trade(self, trade_data: dict) -> None:
        await self.broadcast("trade", trade_data)

    async def broadcast_status(self, status_data: dict) -> None:
        await self.broadcast("status", status_data)


ws_manager = WebSocketManager()
