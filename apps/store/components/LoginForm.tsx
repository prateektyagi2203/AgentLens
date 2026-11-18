"use client";

import { useState, type FormEvent } from "react";

export default function LoginForm() {
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const [message, setMessage] = useState("");

  async function send(e: FormEvent) {
    e.preventDefault();
    const res = await fetch("/api/otp/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: `+91${phone.replace(/\D/g, "")}`, purpose: "login" }),
    });
    if (res.ok) {
      setSent(true);
      setMessage("We have sent an OTP to your mobile number.");
    } else setMessage("Please enter a valid 10-digit mobile number.");
  }

  async function verify(e: FormEvent) {
    e.preventDefault();
    const res = await fetch("/api/otp/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ otp, purpose: "login" }),
    });
    if (res.ok) {
      const next = new URLSearchParams(window.location.search).get("next");
      window.location.assign(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } else setMessage("Incorrect OTP. Please try again.");
  }

  return (
    <div className="mx-auto max-w-sm space-y-4 rounded-xl border border-stone-200 bg-white p-6">
      <h1 className="font-serif text-2xl font-bold">Login or sign up</h1>
      {!sent ? (
        <form onSubmit={send} className="space-y-3">
          <div className="flex">
            <span className="rounded-l border border-r-0 border-stone-300 bg-stone-100 px-3 py-2 text-sm">+91</span>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} type="tel" inputMode="numeric" maxLength={10}
              placeholder="10-digit mobile number" aria-label="Mobile number" data-testid="login-phone"
              className="w-full rounded-r border border-stone-300 px-3 py-2" />
          </div>
          <button type="submit" className="w-full rounded bg-rust-700 py-2 font-semibold text-white">Send OTP</button>
        </form>
      ) : (
        <form onSubmit={verify} className="space-y-3">
          <input value={otp} onChange={(e) => setOtp(e.target.value)} inputMode="numeric" maxLength={6}
            placeholder="Enter 6-digit OTP" aria-label="OTP" data-testid="login-otp"
            className="w-full rounded border border-stone-300 px-3 py-2" />
          <button type="submit" className="w-full rounded bg-rust-700 py-2 font-semibold text-white">Verify and continue</button>
        </form>
      )}
      {message && <p role="status" className="text-sm text-stone-600">{message}</p>}
    </div>
  );
}
