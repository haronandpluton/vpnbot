from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

try:
    from app.database.session import async_session_maker as session_factory
except ImportError:
    from app.database.session import SessionLocal as session_factory

from app.services.order_expiration_service import OrderExpirationService


async def main() -> None:
    async with session_factory() as session:
        result = await OrderExpirationService(session).expire_due_orders()

        print("status:", result.status)
        print("checked_at:", result.checked_at)
        print("expired_count:", result.expired_count)

        for item in result.expired_items:
            print(
                f"expired order_id={item.order_id} "
                f"user_id={item.user_id} "
                f"{item.old_status}->{item.new_status} "
                f"expires_at={item.expires_at}"
            )


if __name__ == "__main__":
    asyncio.run(main())