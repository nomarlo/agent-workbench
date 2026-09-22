import {getOrder} from '../../api/src/client';

export async function loadOrderPage(orderId: number): Promise<string> {
  const order = await getOrder(orderId);
  return `Order ${order.id}: ${order.status}`;
}
