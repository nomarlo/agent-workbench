from shop.orders.models import Order


def serialize_order(order: Order) -> dict:
    return {"id": order.id, "total": order.total, "status": order.status}
