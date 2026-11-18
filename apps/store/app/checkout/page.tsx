import CheckoutForm from "../../components/CheckoutForm";
import SLink from "../../components/SLink";
import { formatINR } from "../../lib/format";
import { overlays, phoneValid, readToggles } from "../../lib/friction";
import { pageContext } from "../../lib/page-context";
import { cartValue } from "../../lib/state";

export const metadata = { title: "Checkout | Desi Threads (TEST STORE)" };

export default async function CheckoutPage() {
  const { state } = await pageContext();
  const toggles = readToggles();

  if (state.cart.length === 0) {
    return (
      <div className="py-12 text-center">
        <h1 className="font-serif text-3xl font-bold">Nothing to check out</h1>
        <SLink href="/" className="mt-4 inline-block text-rust-700 underline">Continue shopping</SLink>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-1 font-serif text-3xl font-bold">Checkout</h1>
      <p className="mb-6 text-sm text-stone-500">{state.cart.length} item(s) · Total {formatINR(cartValue(state))} · Test mode, no real payment</p>
      <CheckoutForm
        total={formatINR(cartValue(state))}
        captcha={overlays(toggles).captcha}
        strictPhone={!phoneValid(toggles, "9876543210")}
      />
    </div>
  );
}
