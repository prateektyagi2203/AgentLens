"use client";

import { useEffect, useState, type FormEvent } from "react";
import type { Variant } from "../lib/catalog";
import { formatINR } from "../lib/format";
import SLink from "./SLink";
import { AppInterstitial, PincodeModal } from "./Overlays";

interface Props {
  product: {
    id: string;
    slug: string;
    sizes: string[];
    colours: string[];
    /** Present only when the server renders stock (F03 off). */
    variants: Variant[] | null;
  };
  /** True when price and stock are already in the server HTML. */
  serverPrice: boolean;
  initialPincodeOk: boolean;
  pincodeModal: boolean;
  appInterstitial: boolean;
  closeDelayMs: number;
}

interface Alternatives {
  variants: Variant[];
}

export default function PdpPurchase(props: Props) {
  const { product, serverPrice } = props;
  const [price, setPrice] = useState<{ price: number; mrp: number } | null>(null);
  const [variants, setVariants] = useState<Variant[] | null>(product.variants);
  const [colour, setColour] = useState(product.colours.length === 1 ? product.colours[0] : "");
  const [size, setSize] = useState(product.sizes.length === 1 ? product.sizes[0] : "");
  const [availability, setAvailability] = useState<{ ok: boolean; text: string; alternatives?: Alternatives } | null>(null);
  const [pincodeOk, setPincodeOk] = useState(props.initialPincodeOk);
  const [pin, setPin] = useState("");
  const [delivery, setDelivery] = useState("");
  const [cartMsg, setCartMsg] = useState<{ text: string; added?: boolean } | null>(null);

  // F03: price and stock are only fetched by client-side JS.
  useEffect(() => {
    if (serverPrice) return;
    let cancelled = false;
    fetch(`/api/products/${product.id}/variants`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        setPrice({ price: d.price, mrp: d.mrp });
        setVariants(d.variants);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [product.id, serverPrice]);

  async function checkVariant(nextSize: string, nextColour: string) {
    if (!nextSize || !nextColour) return;
    setAvailability(null);
    const q = new URLSearchParams({ size: nextSize, colour: nextColour });
    const res = await fetch(`/api/products/${product.id}/variants?${q}`);
    const data = await res.json().catch(() => ({}));
    if (res.status === 409) setAvailability({ ok: false, text: "This item is out of stock." });
    else if (res.ok && data.available === false) {
      setAvailability({ ok: false, text: "This size/colour is out of stock. Try another option:", alternatives: data.alternatives });
    } else if (res.ok) setAvailability({ ok: true, text: "In stock" });
  }

  function choose(nextSize: string, nextColour: string) {
    setSize(nextSize);
    setColour(nextColour);
    void checkVariant(nextSize, nextColour);
  }

  async function checkPincode(e: FormEvent) {
    e.preventDefault();
    const res = await fetch(`/api/serviceability?pincode=${encodeURIComponent(pin)}`);
    const data = await res.json();
    if (res.ok) {
      setPincodeOk(true);
      setDelivery(`Delivery in ${data.eta_days} days. Cash on delivery available.`);
    } else setDelivery("Sorry, we do not deliver to this pincode.");
  }

  async function addToCart() {
    if (!size || !colour) {
      setCartMsg({ text: "Please select a size and colour." });
      return;
    }
    const res = await fetch("/api/cart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_id: product.id, size, colour, qty: 1 }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 201) setCartMsg({ text: "Added to your cart.", added: true });
    else if (res.status === 401) window.location.assign(`/login?next=${encodeURIComponent(`/p/${product.slug}`)}`);
    else if (data.error_code === "PINCODE_REQUIRED") {
      setPincodeOk(false);
      setCartMsg({ text: "Please enter your delivery pincode to continue." });
    } else if (data.error_code === "OUT_OF_STOCK") setCartMsg({ text: "Sorry, this item is out of stock." });
    else setCartMsg({ text: "Could not add to cart. Please try again." });
  }

  const stockFor = (s: string) => (variants && colour ? variants.find((v) => v.size === s && v.colour === colour) : null);

  return (
    <div className="space-y-5">
      {props.appInterstitial && <AppInterstitial closeDelayMs={props.closeDelayMs} />}
      {props.pincodeModal && !pincodeOk && (
        <PincodeModal
          onValid={(_, eta) => {
            setPincodeOk(true);
            setDelivery(`Delivery in ${eta} days. Cash on delivery available.`);
          }}
        />
      )}

      {!serverPrice && (
        <div data-testid="client-price" aria-live="polite">
          {price ? (
            <>
              <p className="text-2xl font-semibold">
                {formatINR(price.price)} <span className="text-base font-normal text-stone-400 line-through">{formatINR(price.mrp)}</span>
              </p>
              {variants && (
                <p className="mt-1 text-sm text-green-700" data-testid="client-stock">
                  {variants.some((v) => v.stock > 0) ? "In stock" : "Out of stock"}
                </p>
              )}
            </>
          ) : (
            <p className="h-8 w-40 animate-pulse rounded bg-stone-200" aria-label="Loading price" />
          )}
        </div>
      )}

      <div>
        <p className="mb-2 text-sm font-medium">Colour: <span className="font-normal">{colour || "Select"}</span></p>
        <div className="flex flex-wrap gap-2">
          {product.colours.map((c) => (
            <button key={c} type="button" aria-pressed={colour === c} data-testid={`colour-${c}`}
              onClick={() => choose(size, c)}
              className={`rounded border px-3 py-1 text-sm ${colour === c ? "border-rust-700 bg-rust-50 text-rust-800" : "border-stone-300"}`}>
              {c}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">Size: <span className="font-normal">{size || "Select"}</span></p>
        <div className="flex flex-wrap gap-2">
          {product.sizes.map((s) => {
            const v = stockFor(s);
            return (
              <button key={s} type="button" aria-pressed={size === s} data-testid={`size-${s}`}
                onClick={() => choose(s, colour)}
                className={`min-w-12 rounded border px-3 py-1 text-sm ${size === s ? "border-rust-700 bg-rust-50 text-rust-800" : "border-stone-300"} ${v && v.stock === 0 ? "text-stone-400" : ""}`}>
                {s}
              </button>
            );
          })}
        </div>
      </div>

      {availability && (
        <div role="status" data-testid="availability" className={availability.ok ? "text-sm text-green-700" : "text-sm text-red-700"}>
          <p>{availability.text}</p>
          {availability.alternatives && (
            <ul className="mt-2 flex flex-wrap gap-2 text-stone-700">
              {availability.alternatives.variants.slice(0, 8).map((v) => (
                <li key={v.sku}>
                  <button type="button" onClick={() => choose(v.size, v.colour)} className="rounded border border-stone-300 px-2 py-1 text-xs">
                    {v.size} / {v.colour}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <form onSubmit={checkPincode} className="flex items-center gap-2" aria-label="Check delivery">
        <input value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric" maxLength={6}
          placeholder="Delivery pincode" aria-label="Delivery pincode" data-testid="pincode-input"
          className="w-40 rounded border border-stone-300 px-3 py-2 text-sm" />
        <button type="submit" className="rounded border border-rust-700 px-3 py-2 text-sm font-medium text-rust-700">Check</button>
        {delivery && <span className="text-sm text-stone-600" data-testid="delivery-info">{delivery}</span>}
      </form>

      <div>
        <button type="button" onClick={addToCart} data-testid="add-to-cart"
          className="w-full rounded bg-rust-700 py-3 font-semibold text-white hover:bg-rust-800 md:w-auto md:px-12">
          Add to cart
        </button>
        {cartMsg && (
          <p role="status" data-testid="cart-message" className="mt-2 text-sm">
            {cartMsg.text}{" "}
            {cartMsg.added && <SLink href="/cart" className="font-medium text-rust-700 underline">View cart</SLink>}
          </p>
        )}
      </div>
    </div>
  );
}
