"use client";

import { useEffect, useState } from "react";

/** F07: full-screen "get the app" interstitial on the first PDP view; the close button appears after a delay. */
export function AppInterstitial({ closeDelayMs }: { closeDelayMs: number }) {
  const [open, setOpen] = useState(false);
  const [canClose, setCanClose] = useState(false);

  useEffect(() => {
    if (sessionStorage.getItem("dt_app_seen")) return;
    sessionStorage.setItem("dt_app_seen", "1");
    setOpen(true);
    const t = setTimeout(() => setCanClose(true), closeDelayMs);
    return () => clearTimeout(t);
  }, [closeDelayMs]);

  if (!open) return null;
  return (
    <div role="dialog" aria-modal="true" aria-label="Get the app" data-testid="app-interstitial"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-rust-700 p-8 text-center text-white">
      {canClose && (
        <button type="button" onClick={() => setOpen(false)} aria-label="Close" data-testid="app-interstitial-close"
          className="absolute right-4 top-4 rounded-full border border-white/60 px-3 py-1 text-lg">
          ×
        </button>
      )}
      <h2 className="font-serif text-4xl font-bold">Get the app for 10% off</h2>
      <p className="mt-3 max-w-sm text-white/90">Faster checkout, app-only drops and your first order 10% cheaper.</p>
      <button type="button" className="mt-8 rounded-full bg-white px-8 py-3 font-semibold text-rust-800">
        Download the app
      </button>
    </div>
  );
}

/** F08: spin-the-wheel email-capture popup covering the landing page. */
export function SpinWheel() {
  const [open, setOpen] = useState(false);
  const [spun, setSpun] = useState(false);

  useEffect(() => {
    if (sessionStorage.getItem("dt_spin_seen")) return;
    sessionStorage.setItem("dt_spin_seen", "1");
    setOpen(true);
  }, []);

  if (!open) return null;
  return (
    <div role="dialog" aria-modal="true" aria-label="Spin the wheel" data-testid="spin-wheel"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-8 text-center">
        <h2 className="font-serif text-3xl font-bold text-rust-700">Spin to win!</h2>
        <div className="mx-auto my-5 h-32 w-32 rounded-full border-8 border-rust-600 bg-[conic-gradient(#b9532c_0_25%,#f5e6d8_0_50%,#b9532c_0_75%,#f5e6d8_0)]" />
        {spun ? (
          <p className="text-stone-700">You won 15% off! Check your inbox.</p>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); setSpun(true); }} className="space-y-3">
            <input type="email" required placeholder="Your email address" aria-label="Email address"
              className="w-full rounded border border-stone-300 px-3 py-2" />
            <button type="submit" className="w-full rounded bg-rust-700 py-2 font-semibold text-white">Spin now</button>
          </form>
        )}
        <button type="button" onClick={() => setOpen(false)} className="mt-4 text-xs text-stone-400 underline">
          No thanks
        </button>
      </div>
    </div>
  );
}

/** F05: modal that blocks the PDP until a serviceable pincode is validated. */
export function PincodeModal({ onValid }: { onValid: (pincode: string, eta: number) => void }) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`/api/serviceability?pincode=${encodeURIComponent(pin)}`);
      const data = await res.json();
      if (res.ok) onValid(pin, data.eta_days);
      else setError("Sorry, we do not deliver to this pincode.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Enter your pincode" data-testid="pincode-modal"
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-3 rounded-xl bg-white p-6">
        <h2 className="font-serif text-xl font-bold">Where should we deliver?</h2>
        <p className="text-sm text-stone-600">Enter your pincode to see delivery options and continue shopping.</p>
        <input value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric" maxLength={6}
          placeholder="6-digit pincode" aria-label="Pincode" data-testid="pincode-modal-input"
          className="w-full rounded border border-stone-300 px-3 py-2" />
        {error && <p className="text-sm text-red-700">{error}</p>}
        <button type="submit" disabled={busy || pin.length !== 6}
          className="w-full rounded bg-rust-700 py-2 font-semibold text-white disabled:opacity-50">
          Check
        </button>
      </form>
    </div>
  );
}
