import { save } from '../storage/store';
export function createOrder(id: string, quantity: number) {
  if (quantity <= 0) throw new Error('quantity must be positive');
  return save({ id, quantity });
}
