from app.database.repositories.payments import PaymentRepository

print(PaymentRepository)
print(hasattr(PaymentRepository, "get_by_txid"))
print(hasattr(PaymentRepository, "get_by_provider_payment_id"))
print(hasattr(PaymentRepository, "mark_detected"))
print(hasattr(PaymentRepository, "mark_confirmed"))