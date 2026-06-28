import logging
from decimal import Decimal

from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.database.models.order import Order
from app.payment_adapters.volet_sci.form import (
    build_volet_sci_form_data,
    build_volet_sci_html,
)
from app.payment_core.enums.order_status import OrderStatus


from app.payment_adapters.volet_sci.verifier import (
    VoletSciVerificationError,
    normalize_volet_sci_order_id,
    redact_volet_sci_status_payload,
    verify_volet_sci_status_hash,
)


logger = logging.getLogger(__name__)


class VoletSciWebServer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        app = web.Application()

        app.router.add_get("/volet/pay/{order_id}", self.handle_pay)
        app.router.add_get("/volet/success", self.handle_success)
        app.router.add_get("/volet/fail", self.handle_fail)
        app.router.add_post("/volet/status", self.handle_status)

        self._runner = web.AppRunner(app)
        await self._runner.setup()

        self._site = web.TCPSite(
            self._runner,
            host=self._settings.volet_sci_web_host,
            port=self._settings.volet_sci_web_port,
        )
        await self._site.start()

        logger.info(
            "Volet SCI web server started on %s:%s",
            self._settings.volet_sci_web_host,
            self._settings.volet_sci_web_port,
        )

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            logger.info("Volet SCI web server stopped")

    async def handle_pay(self, request: web.Request) -> web.Response:
        raw_order_id = request.match_info.get("order_id", "")

        try:
            order_id = int(raw_order_id)
        except ValueError:
            return web.Response(
                text="Invalid order id",
                status=400,
                content_type="text/plain",
            )

        async with self._session_factory() as session:
            order = await session.get(Order, order_id)

        if order is None:
            return web.Response(
                text="Order not found",
                status=404,
                content_type="text/plain",
            )

        allowed_statuses = {
            OrderStatus.CREATED,
            OrderStatus.WAITING_PAYMENT,
        }

        if order.status not in allowed_statuses:
            return web.Response(
                text=f"Order is not payable. Current status: {order.status}",
                status=409,
                content_type="text/plain",
            )

        amount: Decimal = order.expected_amount or order.price_usd
        volet_order_id = f"order_{order.id}"

        try:
            form_data = build_volet_sci_form_data(
                settings=self._settings,
                order_id=volet_order_id,
                amount=amount,
                comments=f"VPN subscription 30 days. Order #{order.id}",
                currency=self._settings.volet_sci_default_currency,
            )
        except ValueError as exc:
            logger.exception("Volet SCI form configuration error")
            return web.Response(
                text=f"Payment configuration error: {exc}",
                status=500,
                content_type="text/plain",
            )

        html = build_volet_sci_html(
            form_data,
            title="Оплата VPN через Volet",
            submit_text="Перейти к оплате Volet",
            auto_submit=True,
        )

        return web.Response(
            text=html,
            content_type="text/html",
            charset="utf-8",
        )

    async def handle_success(self, request: web.Request) -> web.Response:
        html = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Платёж отправлен</title>
</head>
<body>
  <h1>Платёж отправлен</h1>
  <p>Если оплата прошла успешно, вернитесь в Telegram-бот и проверьте подписку.</p>
</body>
</html>
"""
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def handle_fail(self, request: web.Request) -> web.Response:
        html = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Платёж не завершён</title>
</head>
<body>
  <h1>Платёж не завершён</h1>
  <p>Вернитесь в Telegram-бот и создайте новый заказ или обратитесь в поддержку.</p>
</body>
</html>
"""
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def handle_status(self, request: web.Request) -> web.Response:
        raw_data = await request.post()
        data = {str(key): str(value) for key, value in raw_data.items()}

        safe_payload = redact_volet_sci_status_payload(data)

        try:
            verification = verify_volet_sci_status_hash(
                data,
                password=self._settings.volet_sci_password,
            )
        except VoletSciVerificationError as exc:
            logger.warning(
                "Volet SCI status callback rejected: %s payload=%s",
                exc,
                safe_payload,
            )
            return web.Response(
                text="INVALID",
                status=400,
                content_type="text/plain",
            )

        if not verification.is_valid:
            logger.warning(
                "Volet SCI status callback invalid hash: payload=%s",
                safe_payload,
            )
            return web.Response(
                text="INVALID_HASH",
                status=400,
                content_type="text/plain",
            )

        try:
            order_id = normalize_volet_sci_order_id(
                data.get("ac_order_id", ""),
            )
        except VoletSciVerificationError as exc:
            logger.warning(
                "Volet SCI status callback invalid order id: %s payload=%s",
                exc,
                safe_payload,
            )
            return web.Response(
                text="INVALID_ORDER_ID",
                status=400,
                content_type="text/plain",
            )

        transaction_status = data.get("ac_transaction_status", "").strip().upper()

        logger.info(
            "Volet SCI status callback verified: order_id=%s status=%s transfer=%s hash_variant=%s",
            order_id,
            transaction_status,
            data.get("ac_transfer", ""),
            verification.variant,
        )

        return web.Response(text="OK", content_type="text/plain")