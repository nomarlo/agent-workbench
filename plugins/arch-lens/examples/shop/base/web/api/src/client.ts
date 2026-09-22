export interface Order {
  id: number;
  total: number;
  status: string;
}

export async function getOrder(orderId: number): Promise<Order> {
  const response = await fetch(`/api/orders/${orderId}`);
  return response.json();
}
