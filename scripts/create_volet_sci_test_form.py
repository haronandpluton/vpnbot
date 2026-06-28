from pathlib import Path

from app.config.settings import get_settings
from app.payment_adapters.volet_sci.form import (
    build_volet_sci_form_data,
    build_volet_sci_html,
)


def main() -> None:
    settings = get_settings()

    form_data = build_volet_sci_form_data(
        settings=settings,
        order_id="test_order_2",
        amount="4.00",
        comments="VPN subscription 30 days test",
        currency=settings.volet_sci_default_currency,
    )

    html = build_volet_sci_html(
        form_data,
        title="Volet SCI test payment",
        submit_text="Pay 4 USDT via Volet",
        auto_submit=False,
    )

    output_path = Path("volet_sci_test_payment.html")
    output_path.write_text(html, encoding="utf-8")

    print(f"Created: {output_path.resolve()}")
    print("Open this file in browser and press the payment button.")


if __name__ == "__main__":
    main()