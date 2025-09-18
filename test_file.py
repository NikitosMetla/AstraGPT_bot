import asyncio

from utils.payment_for_services import check_payment

payment_id = "305b4e0d-000f-5000-b000-16944209feb1"


print(asyncio.run(check_payment(payment_id)))