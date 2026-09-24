// Synthetic fixture. No framework installation or execution is required.
import { createOrder } from '../domain/orders';
export function postOrder(request: { id: string; quantity: number }) {
  return createOrder(request.id, request.quantity);
}
export const routes = [{ method: 'POST', path: '/orders', handler: postOrder }];
