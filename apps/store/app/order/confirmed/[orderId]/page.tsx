import fs from "node:fs";
import { notFound } from "next/navigation";
import SLink from "../../../../components/SLink";
import { formatINR } from "../../../../lib/format";
import { ordersFile } from "../../../../lib/paths";
import { registry } from "../../../../lib/state";

export const metadata = { title: "Order confirmed | Desi Threads (TEST STORE)" };

function findOrder(orderId: string): { order_id: string; cart_value: number; payment_method: string } | null {
  const mem = registry().orders.get(orderId);
  if (mem) return mem;
  try {
    for (const line of fs.readFileSync(ordersFile(), "utf8").split("\n")) {
      if (!line) continue;
      const o = JSON.parse(line);
      if (o.order_id === orderId) return o;
    }
  } catch {
    // no orders file yet
  }
  return null;
}

export default async function OrderConfirmed({ params }: { params: Promise<{ orderId: string }> }) {
  const order = findOrder((await params).orderId);
  if (!order) notFound();
  return (
    <div className="mx-auto max-w-lg space-y-3 rounded-xl border border-stone-200 bg-white p-8 text-center">
      <h1 className="font-serif text-3xl font-bold text-green-700">Order confirmed</h1>
      <p>Your order number is <span className="font-mono font-semibold" data-testid="order-id">{order.order_id}</span></p>
      <p className="text-stone-600">{formatINR(order.cart_value)} · {order.payment_method}</p>
      <p className="text-sm text-stone-500">This is a test order. Nothing will be shipped or charged.</p>
      <SLink href="/" className="inline-block text-rust-700 underline">Continue shopping</SLink>
    </div>
  );
}
