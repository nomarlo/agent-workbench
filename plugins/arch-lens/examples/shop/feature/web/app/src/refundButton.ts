import {refundOrder} from '../../api/src/client';
import {cardPayments, PaymentMethod, walletPayments} from '../../api/src/payments';

export function paymentMethodFor(kind: string): PaymentMethod {
  return kind === 'wallet' ? walletPayments : cardPayments;
}

export async function requestRefund(orderId: number, amount: number, method: PaymentMethod): Promise<string | null> {
  const confirmed = await method.confirmRefund(orderId, amount);
  if (!confirmed) return null;
  return refundOrder(orderId, amount, `customer request via ${method.label}`);
}
