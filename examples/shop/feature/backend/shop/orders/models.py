from shop.orders.services import REFUND_WINDOW_DAYS


class Manager:
    def create(self, **fields):
        return Order(**fields)

    def get(self, **lookup):
        return Order(**lookup)


class Order:
    objects = Manager()

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def is_refundable(self, age_days: int) -> bool:
        return self.status == "paid" and age_days <= REFUND_WINDOW_DAYS


class Refund:
    objects = Manager()

    def __init__(self, **fields):
        self.__dict__.update(fields)
