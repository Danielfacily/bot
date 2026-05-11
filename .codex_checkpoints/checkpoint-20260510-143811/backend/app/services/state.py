from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock


@dataclass
class RuntimeState:
    running: bool = False
    kill_switch: bool = False
    hot_coins: list[dict] = field(default_factory=list)
    balance: float = 10_000
    last_scan_at: datetime | None = None
    trailing_peak_roi: dict[int, float] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def update_hot_coins(self, coins: list[dict]) -> None:
        with self.lock:
            self.hot_coins = coins
            self.last_scan_at = datetime.utcnow()


runtime_state = RuntimeState()
