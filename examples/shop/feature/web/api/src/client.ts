export interface Order {
  id: number;
  total: number;
  status: string;
}

export async function getOrder(orderId: number): Promise<Order> {
  const response = await fetch(`/api/orders/${orderId}`);
  return response.json();
}

export async function refundOrder(orderId: number, amount: number, reason: string): Promise<string> {
  const response = await fetch(`/api/orders/${orderId}/refund`, {method: 'POST', body: JSON.stringify({amount, reason})});
  return (await response.json()).refund;
}
