import SLink from "../../components/SLink";
import { formatINR } from "../../lib/format";
import { pageContext } from "../../lib/page-context";
import { cartValue } from "../../lib/state";

export const metadata = { title: "Your cart | Desi Threads (TEST STORE)" };

export default async function CartPage() {
  const { state } = await pageContext();
  const total = cartValue(state);

  if (state.cart.length === 0) {
    return (
      <div className="py-12 text-center">
        <h1 className="font-serif text-3xl font-bold">Your cart is empty</h1>
        <SLink href="/" className="mt-4 inline-block text-rust-700 underline">Continue shopping</SLink>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <h1 className="mb-6 font-serif text-3xl font-bold">Your cart</h1>
      <ul className="divide-y divide-stone-200 rounded border border-stone-200 bg-white">
        {state.cart.map((item) => (
          <li key={`${item.product_id}-${item.size}-${item.colour}`} className="flex items-center justify-between gap-4 p-4" data-testid="cart-line">
            <div>
              <SLink href={`/p/${item.slug}`} className="font-medium hover:text-rust-700">{item.name}</SLink>
              <p className="text-sm text-stone-500">Size {item.size} · {item.colour} · Qty {item.qty}</p>
            </div>
            <p className="font-semibold" data-testid="cart-line-price">{formatINR(item.unit_price * item.qty)}</p>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex items-center justify-between">
        <p className="text-lg">Total: <span className="font-semibold" data-testid="cart-total">{formatINR(total)}</span></p>
        <SLink href="/checkout" className="rounded bg-rust-700 px-8 py-3 font-semibold text-white hover:bg-rust-800">
          Proceed to checkout
        </SLink>
      </div>
    </div>
  );
}
