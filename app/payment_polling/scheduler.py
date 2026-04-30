async def start_polling():
    while True:
        await run_polling_cycle()
        await asyncio.sleep(settings.POLLING_INTERVAL)