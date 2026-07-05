import asyncio
import json
import sys
from datetime import timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from app.database.models import Subscription  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.payment_core.enums.subscription_status import SubscriptionStatus  # noqa: E402


OUTPUT_PATH = PROJECT_ROOT / "deploy" / "vpn-subscription" / "subscriptions_meta.generated.json"


def to_unix_timestamp(dt) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return int(dt.timestamp())


async def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with SessionLocal() as session:
        stmt = select(Subscription).where(
            Subscription.status.in_(
                [
                    SubscriptionStatus.ACTIVE,
                    SubscriptionStatus.EXPIRED,
                ]
            )
        )

        result = await session.execute(stmt)
        subscriptions = result.scalars().all()

    data = {}

    for subscription in subscriptions:
        data[subscription.uuid] = {
            "expire": to_unix_timestamp(subscription.expires_at),
            "upload": 0,
            "download": 0,
            "total": 0,
        }

    OUTPUT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Exported {len(data)} subscriptions")
    print(f"Saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())