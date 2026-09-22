from shop.core.http import Request, Response
from shop.orders import services
from shop.orders.models import Order
from shop.orders.serializers import serialize_order


class OrderView:
    def get(self, request: Request, order_id: int) -> Response:
        return Response(serialize_order(Order.objects.get(id=order_id)))

    def post(self, request: Request) -> Response:
        order = services.place_order(request.data["customer_id"], request.data["total"], request.data["source"])
        return Response(serialize_order(order), status=201)
