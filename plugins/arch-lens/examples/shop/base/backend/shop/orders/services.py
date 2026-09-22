from shop.orders.models import Order
from shop.orders.tasks import notify_customer
from shop.payments import gateway


def place_order(customer_id: int, total: int, source: str) -> Order:
    charge_id = gateway.charge(total, "usd", source)
    order = Order.objects.create(customer_id=customer_id, total=total, charge_id=charge_id, status="paid")
    notify_customer.send(order.id, "order-placed")
    return order
