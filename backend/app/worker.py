import asyncio
from app.main import scanner_loop, strategy_loop


async def main() -> None:
    await asyncio.gather(scanner_loop(), strategy_loop())


if __name__ == "__main__":
    asyncio.run(main())
