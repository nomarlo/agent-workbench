class Manager:
    def create(self, **fields):
        return Order(**fields)

    def get(self, **lookup):
        return Order(**lookup)


class Order:
    objects = Manager()

    def __init__(self, **fields):
        self.__dict__.update(fields)
