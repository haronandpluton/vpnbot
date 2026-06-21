import asyncio
import sys

sys.path.insert(0, ".")

try:
    from app.database.session import async_session_maker as session_factory
except ImportError:
    from app.database.session import SessionLocal as session_factory

from app.services.subscription_expiration_service import SubscriptionExpirationService


async def main() -> None:
    async with session_factory() as session:
        result = await SubscriptionExpirationService(session).expire_due_subscriptions(
            sync_metadata=True,
        )

        print("status:", result.status)
        print("checked_at:", result.checked_at)
        print("expired_count:", result.expired_count)
        print("sync_status:", result.sync_status)

        if result.sync_error:
            print("sync_error:", result.sync_error)

        for item in result.expired_items:
            print(
                f"expired subscription_id={item.subscription_id} "
                f"user_id={item.user_id} "
                f"uuid={item.uuid} "
                f"expires_at={item.expires_at}"
            )


if __name__ == "__main__":
    asyncio.run(main())
