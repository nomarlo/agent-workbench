export interface PaymentMethod {
  label: string;
  confirmRefund(orderId: number, amount: number): Promise<boolean>;
}

export const cardPayments: PaymentMethod = {
  label: 'card',
  confirmRefund: async (orderId, amount) => amount > 0 && orderId > 0,
};

export const walletPayments: PaymentMethod = {
  label: 'wallet',
  confirmRefund: async (orderId, amount) => amount <= 500 && orderId > 0,
};
