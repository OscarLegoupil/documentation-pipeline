declare const runtimeAdapter: { put(value: unknown): Promise<void> };
export async function save(order: { id: string; quantity: number }) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try { await runtimeAdapter.put(order); return order; }
    catch (error) { if (attempt === 2) throw error; }
  }
}
// Adapter selection and deployed storage name are not present in this scope.
