from shop.orders.models import Order, Refund
from shop.orders.money import to_cents
from shop.orders.tasks import notify_customer
from shop.payments import gateway

REFUND_WINDOW_DAYS = 30


def place_order(customer_id: int, total: int, source: str) -> Order:
    charge_id = gateway.charge(total, "usd", source)
    order = Order.objects.create(customer_id=customer_id, total=total, charge_id=charge_id, status="paid")
    notify_customer.send(order.id, "order-placed")
    return order


def refund_order(order_id: int, amount: float, reason: str) -> Refund:
    order = Order.objects.get(id=order_id)
    if not order.is_refundable(age_days=0):
        raise ValueError("order is outside the refund window")
    refund_id = gateway.refund(order.charge_id, to_cents(amount), reason)
    refund = Refund.objects.create(order_id=order_id, gateway_id=refund_id, reason=reason)
    notify_customer.send(order_id, "order-refunded")
    return refund
