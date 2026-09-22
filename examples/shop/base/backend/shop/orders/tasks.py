from shop.core.queue import actor


@actor
def notify_customer(order_id: int, template: str):
    print(f"notify {order_id} with {template}")
