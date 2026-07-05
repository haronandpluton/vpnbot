from __future__ import annotations

import asyncio

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.payment_polling.loop import PaymentPollingLoop


async def run_polling_cycle() -> list:
    async with SessionLocal() as session:
        return await PaymentPollingLoop(session).run_once()


async def start_polling() -> None:
    settings = get_settings()

    while True:
        await run_polling_cycle()
        await asyncio.sleep(settings.payment_poll_interval_seconds)