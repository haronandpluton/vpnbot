from app.database.repositories.payment_events import PaymentEventRepository

print(PaymentEventRepository)
print(hasattr(PaymentEventRepository, "get_by_external_event_id"))
print(hasattr(PaymentEventRepository, "attach_payment"))
print(hasattr(PaymentEventRepository, "mark_processed"))