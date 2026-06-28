import hashlib
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from typing import Any

from app.config.settings import Settings


@dataclass(frozen=True)
class VoletSciFormData:
    action_url: str
    account_email: str
    sci_name: str
    amount: str
    currency: str
    order_id: str
    sign: str
    comments: str = ""
    client_lang: str = "en"

    def fields(self) -> dict[str, str]:
        result = {
            "ac_account_email": self.account_email,
            "ac_sci_name": self.sci_name,
            "ac_amount": self.amount,
            "ac_currency": self.currency,
            "ac_order_id": self.order_id,
            "ac_sign": self.sign,
            "ac_client_lang": self.client_lang,
        }

        if self.comments:
            result["ac_comments"] = self.comments

        return result


def format_volet_amount(amount: Decimal | int | float | str) -> str:
    decimal_amount = Decimal(str(amount))
    return str(decimal_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate_volet_sci_sign(
    *,
    account_email: str,
    sci_name: str,
    amount: str,
    currency: str,
    password: str,
    order_id: str,
) -> str:
    source = f"{account_email}:{sci_name}:{amount}:{currency}:{password}:{order_id}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_volet_sci_form_data(
    *,
    settings: Settings,
    order_id: int | str,
    amount: Decimal | int | float | str,
    comments: str = "",
    currency: str | None = None,
) -> VoletSciFormData:
    action_url = settings.volet_sci_url.strip()
    account_email = settings.volet_sci_account_email.strip()
    sci_name = settings.volet_sci_name.strip()
    password = settings.volet_sci_password.strip()
    payment_currency = (currency or settings.volet_sci_default_currency).strip()

    if not action_url:
        raise ValueError("VOLET_SCI_URL is empty")

    if not account_email:
        raise ValueError("VOLET_SCI_ACCOUNT_EMAIL is empty")

    if not sci_name:
        raise ValueError("VOLET_SCI_NAME is empty")

    if not password:
        raise ValueError("VOLET_SCI_PASSWORD is empty")

    if not payment_currency:
        raise ValueError("VOLET_SCI_DEFAULT_CURRENCY is empty")

    normalized_amount = format_volet_amount(amount)
    normalized_order_id = str(order_id)

    sign = calculate_volet_sci_sign(
        account_email=account_email,
        sci_name=sci_name,
        amount=normalized_amount,
        currency=payment_currency,
        password=password,
        order_id=normalized_order_id,
    )

    return VoletSciFormData(
        action_url=action_url,
        account_email=account_email,
        sci_name=sci_name,
        amount=normalized_amount,
        currency=payment_currency,
        order_id=normalized_order_id,
        sign=sign,
        comments=comments,
    )


def build_volet_sci_html(
    form_data: VoletSciFormData,
    *,
    title: str = "Volet payment",
    submit_text: str = "Pay with Volet",
    auto_submit: bool = False,
) -> str:
    hidden_inputs = "\n".join(
        f'    <input type="hidden" name="{escape(name)}" value="{escape(value)}">'
        for name, value in form_data.fields().items()
    )

    auto_submit_script = ""
    if auto_submit:
        auto_submit_script = """
  <script>
    window.addEventListener("load", function () {
      document.getElementById("volet-payment-form").submit();
    });
  </script>
"""

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <h1>{escape(title)}</h1>
  <p>Order ID: {escape(form_data.order_id)}</p>
  <p>Amount: {escape(form_data.amount)} {escape(form_data.currency)}</p>

  <form id="volet-payment-form" method="post" action="{escape(form_data.action_url)}">
{hidden_inputs}
    <button type="submit">{escape(submit_text)}</button>
  </form>
{auto_submit_script}
</body>
</html>
"""


def build_volet_sci_debug_payload(form_data: VoletSciFormData) -> dict[str, Any]:
    fields = form_data.fields().copy()

    if "ac_sign" in fields:
        fields["ac_sign"] = "***"

    return {
        "action_url": form_data.action_url,
        "fields": fields,
    }