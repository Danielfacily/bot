import asyncio
import json
import websockets
from app.config import get_settings


class WebSocketManager:
    def __init__(self):
        self.settings = get_settings()
        self.last_messages: dict[str, dict] = {}

    async def watch_mini_tickers(self) -> None:
        url = f"{self.settings.binance_ws_url}/ws/!miniTicker@arr"
        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as websocket:
                    async for message in websocket:
                        rows = json.loads(message)
                        for row in rows:
                            symbol = row.get("s")
                            if symbol and symbol.endswith("USDT"):
                                self.last_messages[symbol] = row
            except Exception:
                await asyncio.sleep(10)
