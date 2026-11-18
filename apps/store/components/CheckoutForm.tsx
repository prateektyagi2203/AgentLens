"use client";

import { useState, type FormEvent } from "react";

interface Props {
  total: string;
  captcha: boolean;
  strictPhone: boolean;
}

export default function CheckoutForm({ total, captcha, strictPhone }: Props) {
  const [form, setForm] = useState({ name: "", phone: "", address: "", pincode: "", method: "COD", captcha: "", codOtp: "" });
  const [needOtp, setNeedOtp] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [captchaKey, setCaptchaKey] = useState(0);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function sendCodOtp() {
    await fetch("/api/otp/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: form.phone, purpose: "cod" }),
    });
    setError("We have sent an OTP to your phone. Enter it below to confirm your COD order.");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          phone: form.phone,
          address: `${form.address} ${form.pincode}`.trim(),
          payment_method: form.method,
          captcha_answer: form.captcha,
          cod_otp: form.codOtp,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 201) {
        window.location.assign(`/order/confirmed/${data.order_id}`);
        return;
      }
      if (data.error_code === "COD_OTP_REQUIRED") {
        setNeedOtp(true);
        if (!needOtp) await sendCodOtp();
        else setError("Incorrect OTP. Please try again.");
      } else if (data.error_code === "CAPTCHA_REQUIRED") {
        setError("Please type the characters shown in the image.");
        setCaptchaKey((k) => k + 1);
      } else if (data.error_code === "PHONE_FORMAT") {
        setError(strictPhone ? "Enter your phone as +91 XXXXX XXXXX." : "Enter a valid phone number.");
      } else if (data.error_code === "CART_EMPTY") setError("Your cart is empty.");
      else setError("Please fill in all the fields.");
    } finally {
      setBusy(false);
    }
  }

  const input = "w-full rounded border border-stone-300 px-3 py-2";
  return (
    <form onSubmit={submit} className="max-w-xl space-y-4" aria-label="Checkout">
      <label className="block text-sm">Full name
        <input className={input} value={form.name} onChange={set("name")} autoComplete="name" data-testid="co-name" />
      </label>
      <label className="block text-sm">Mobile number
        <input className={input} value={form.phone} onChange={set("phone")} type="tel" autoComplete="tel"
          placeholder={strictPhone ? "+91 XXXXX XXXXX" : "+91 10-digit mobile number"} data-testid="co-phone" />
      </label>
      <label className="block text-sm">Address
        <textarea className={input} value={form.address} onChange={set("address")} rows={3} data-testid="co-address" />
      </label>
      <label className="block text-sm">Pincode
        <input className={input} value={form.pincode} onChange={set("pincode")} inputMode="numeric" maxLength={6} data-testid="co-pincode" />
      </label>

      <fieldset className="space-y-1 text-sm">
        <legend className="mb-1 font-medium">Payment method</legend>
        {[["COD", "Cash on delivery"], ["UPI", "UPI"], ["CARD", "Credit / debit card"]].map(([v, label]) => (
          <label key={v} className="flex items-center gap-2">
            <input type="radio" name="payment" value={v} checked={form.method === v}
              onChange={() => setForm({ ...form, method: v })} data-testid={`pay-${v}`} />
            {label}
          </label>
        ))}
        <p className="text-xs text-stone-500">Test mode: payments are simulated.</p>
      </fieldset>

      {captcha && (
        <label className="block text-sm">Type the characters you see
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img key={captchaKey} src={`/api/captcha?n=${captchaKey}`} alt="Captcha" width={160} height={56} className="my-2 rounded border border-stone-300" />
          <input className={input} value={form.captcha} onChange={set("captcha")} data-testid="co-captcha" />
        </label>
      )}

      {needOtp && (
        <label className="block text-sm">COD confirmation OTP
          <input className={input} value={form.codOtp} onChange={set("codOtp")} inputMode="numeric" maxLength={6} data-testid="co-cod-otp" />
        </label>
      )}

      {error && <p role="alert" className="text-sm text-red-700" data-testid="co-error">{error}</p>}
      <button type="submit" disabled={busy} data-testid="co-submit"
        className="w-full rounded bg-rust-700 py-3 font-semibold text-white hover:bg-rust-800 disabled:opacity-50">
        Place order · {total}
      </button>
    </form>
  );
}
