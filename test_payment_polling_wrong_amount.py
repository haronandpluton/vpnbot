async def test_polling_wrong_amount_does_not_activate_order():
    """
    Arrange:
    - создать user
    - создать order waiting_payment
    - expected_amount = 10
    - mock adapter возвращает tx amount = 5

    Act:
    - запустить polling processor

    Assert:
    - payment_event создан
    - payment.status == invalid
    - order.status == waiting_payment
    - subscription не создана / не active
    - vpn config не создан
    """