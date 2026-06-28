import json
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

from app.services.payment_activation_service import PaymentActivationService

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

        app.router.add_get("/", self.handle_home)
        app.router.add_get("/terms", self.handle_terms)
        app.router.add_get("/privacy", self.handle_privacy)
        app.router.add_get("/support", self.handle_support)

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

    def _html_response(self, title: str, body: str) -> web.Response:
        html = f"""<!doctype html>
    <html lang="ru">
    <head>
      <meta charset="utf-8">
      <title>{title}</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f6f7f9;
      color: #111827;
      line-height: 1.6;
    }}
    header {{
      background: #111827;
      color: white;
      padding: 24px;
    }}
    main {{
      max-width: 920px;
      margin: 0 auto;
      padding: 32px 20px;
      background: white;
      min-height: 70vh;
    }}
    nav a {{
      color: white;
      margin-right: 16px;
      text-decoration: none;
    }}
    a {{
      color: #2563eb;
    }}
    .card {{
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      padding: 20px;
      margin: 16px 0;
      background: #fafafa;
    }}
    .button {{
      display: inline-block;
      padding: 12px 18px;
      background: #111827;
      color: white;
      border-radius: 8px;
      text-decoration: none;
      margin-top: 12px;
    }}
    footer {{
      max-width: 920px;
      margin: 0 auto;
      padding: 20px;
      color: #6b7280;
      font-size: 14px;
    }}
      </style>
    </head>
    <body>
      <header>
    <h1>PresentVPN</h1>
    <nav>
      <a href="/">Home</a>
      <a href="/terms">Terms</a>
      <a href="/privacy">Privacy</a>
      <a href="/support">Support</a>
    </nav>
      </header>
      <main>
    {body}
      </main>
      <footer>
    PresentVPN — VPN subscription service. Payments are processed via Volet SCI.
      </footer>
    </body>
    </html>
    """
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    def _support_url(self) -> str:
        support_username = self._settings.support_username.strip().lstrip("@")

        if support_username:
            return f"https://t.me/{support_username}"

        return "https://t.me/VPN_FORBOT"

    async def handle_home(self, request: web.Request) -> web.Response:
        support_url = self._support_url()

        body = f"""
    <h2>VPN access for private internet connection</h2>

    <div class="card">
      <h3>Service</h3>
      <p>
        PresentVPN provides paid VPN subscription access for users who want
        a private and stable internet connection through supported VPN clients.
      </p>
    </div>

    <div class="card">
      <h3>Current plan</h3>
      <p><strong>Plan:</strong> 1 device</p>
      <p><strong>Period:</strong> 30 days</p>
      <p><strong>Price:</strong> 4 USDT</p>
      <p>
        After payment confirmation, the Telegram bot issues a personal VPN
        connection link for the subscription period.
      </p>
    </div>

    <div class="card">
      <h3>How to buy</h3>
      <ol>
        <li>Open the Telegram bot.</li>
        <li>Select the VPN plan.</li>
        <li>Pay the generated order via Volet.</li>
        <li>Return to the bot and receive your VPN access link.</li>
      </ol>
      <a class="button" href="https://t.me/VPN_FORBOT">Open Telegram bot</a>
    </div>

    <div class="card">
      <h3>Support</h3>
      <p>
        If you have payment or connection questions, contact support:
        <a href="{support_url}">{support_url}</a>
      </p>
    </div>
    """
        return self._html_response("PresentVPN — VPN subscription service", body)

    async def handle_terms(self, request: web.Request) -> web.Response:
        support_url = self._support_url()

        body = f"""
    <h2>Terms of Service</h2>

    <p>
      These terms apply to the PresentVPN subscription service.
      By purchasing or using the service, you agree to these terms.
    </p>

    <div class="card">
      <h3>1. Service description</h3>
      <p>
        PresentVPN provides digital VPN access for a limited subscription period.
        The current public plan is VPN access for 1 device for 30 days.
      </p>
    </div>

    <div class="card">
      <h3>2. Payment and activation</h3>
      <p>
        Payment is made through the payment page generated by the Telegram bot.
        After payment confirmation, the system activates the subscription and
        provides a VPN connection link in Telegram.
      </p>
    </div>

    <div class="card">
      <h3>3. Acceptable use</h3>
      <p>
        The service must not be used for illegal activity, fraud, spam,
        attacks, abuse of third-party services, or violation of applicable law.
        Access may be limited or terminated in case of abuse.
      </p>
    </div>

    <div class="card">
      <h3>4. Subscription period</h3>
      <p>
        The subscription is valid for the paid period. When the subscription
        expires, VPN access may be disabled until renewal.
      </p>
    </div>

    <div class="card">
      <h3>5. Support</h3>
      <p>
        For payment or technical questions, contact support:
        <a href="{support_url}">{support_url}</a>
      </p>
    </div>
    """
        return self._html_response("PresentVPN — Terms of Service", body)

    async def handle_privacy(self, request: web.Request) -> web.Response:
        support_url = self._support_url()

        body = f"""
    <h2>Privacy Policy</h2>

    <p>
      This policy explains what data is processed when using PresentVPN.
    </p>

    <div class="card">
      <h3>1. Telegram data</h3>
      <p>
        The service may process Telegram user ID, username, first name,
        language code, order data, subscription status, and technical service
        records required to provide VPN access.
      </p>
    </div>

    <div class="card">
      <h3>2. Payment data</h3>
      <p>
        Payments are processed by Volet. PresentVPN receives payment status
        data required to match a payment with an order and activate the
        subscription.
      </p>
    </div>

    <div class="card">
      <h3>3. Technical data</h3>
      <p>
        The service may store technical logs required for security,
        troubleshooting, payment verification, and subscription management.
      </p>
    </div>

    <div class="card">
      <h3>4. Data use</h3>
      <p>
        Data is used to create orders, verify payments, issue VPN access,
        manage subscriptions, prevent abuse, and provide support.
      </p>
    </div>

    <div class="card">
      <h3>5. Contact</h3>
      <p>
        Privacy and support questions:
        <a href="{support_url}">{support_url}</a>
      </p>
    </div>
    """
        return self._html_response("PresentVPN — Privacy Policy", body)

    async def handle_support(self, request: web.Request) -> web.Response:
        support_url = self._support_url()

        body = f"""
    <h2>Support</h2>

    <div class="card">
      <h3>Contact</h3>
      <p>
        For payment issues, VPN setup questions, subscription problems,
        or access recovery, contact support in Telegram:
      </p>
      <p><a href="{support_url}">{support_url}</a></p>
    </div>

    <div class="card">
      <h3>Before contacting support</h3>
      <p>Please prepare your Telegram account and order ID if available.</p>
    </div>

    <div class="card">
      <h3>Payment status</h3>
      <p>
        After payment, return to the Telegram bot and press
        “Я оплатил / Проверить оплату”.
      </p>
    </div>
    """
        return self._html_response("PresentVPN — Support", body)
    
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
        transfer_id = data.get("ac_transfer", "").strip()

        logger.info(
            "Volet SCI status callback verified: order_id=%s status=%s transfer=%s hash_variant=%s",
            order_id,
            transaction_status,
            transfer_id,
            verification.variant,
        )

        success_statuses = {
            "COMPLETED",
            "SUCCESS",
            "CONFIRMED",
            "PAID",
        }

        if transaction_status not in success_statuses:
            logger.info(
                "Volet SCI callback ignored because status is not final success: order_id=%s status=%s transfer=%s",
                order_id,
                transaction_status,
                transfer_id,
            )
            return web.Response(text="OK", content_type="text/plain")

        try:
            amount = Decimal(data.get("ac_amount", "0"))
        except Exception:
            logger.warning(
                "Volet SCI callback invalid amount: order_id=%s payload=%s",
                order_id,
                safe_payload,
            )
            return web.Response(
                text="INVALID_AMOUNT",
                status=400,
                content_type="text/plain",
            )

        if not transfer_id:
            logger.warning(
                "Volet SCI callback missing transfer id: order_id=%s payload=%s",
                order_id,
                safe_payload,
            )
            return web.Response(
                text="INVALID_TRANSFER",
                status=400,
                content_type="text/plain",
            )

        txid = f"volet:{transfer_id}"
        raw_payload_json = json.dumps(
            safe_payload,
            ensure_ascii=False,
            sort_keys=True,
        )

        async with self._session_factory() as session:
            activation_service = PaymentActivationService(session)

            event, payment, subscription, config_uri = (
                await activation_service.process_confirmed_payment_event_and_activate(
                    order_id=order_id,
                    amount=amount,
                    provider="volet_sci",
                    event_type="payment_confirmed",
                    external_event_id=transfer_id,
                    txid=txid,
                    address_from=data.get("ac_src_wallet", ""),
                    address_to=data.get("ac_dest_wallet", ""),
                    memo_tag=data.get("ac_order_id", ""),
                    confirmations=None,
                    raw_payload=raw_payload_json,
                )
            )

            def _model_id(obj):
                if obj is None:
                    return None

                state = getattr(obj, "_sa_instance_state", None)
                if state is not None and state.identity:
                    return state.identity[0]

                return getattr(obj, "__dict__", {}).get("id")

            event_id = _model_id(event)
            payment_id = _model_id(payment)
            subscription_id = _model_id(subscription)
            has_config_uri = bool(config_uri)

            await session.commit()

        logger.info(
            "Volet SCI payment activation processed: order_id=%s transfer=%s event_id=%s payment_id=%s subscription_id=%s config_uri=%s",
            order_id,
            transfer_id,
            event_id,
            payment_id,
            subscription_id,
            has_config_uri,
        )

        return web.Response(text="OK", content_type="text/plain")