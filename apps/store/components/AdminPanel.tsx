"use client";

import { useState, type FormEvent } from "react";
import { FRICTION_IDS, FRICTION_LABELS, type Toggles } from "../lib/friction-meta";

export function AdminLogin() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (res.ok) window.location.reload();
    else setError("Wrong password.");
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-sm space-y-3 rounded-xl border border-stone-200 bg-white p-6">
      <h1 className="font-serif text-2xl font-bold">Admin</h1>
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password"
        aria-label="Admin password" className="w-full rounded border border-stone-300 px-3 py-2" />
      {error && <p className="text-sm text-red-700">{error}</p>}
      <button type="submit" className="w-full rounded bg-stone-900 py-2 font-semibold text-white">Sign in</button>
    </form>
  );
}

export function AdminPanel({ initial }: { initial: Toggles }) {
  const [toggles, setToggles] = useState<Toggles>(initial);
  const [note, setNote] = useState("");
  const [status, setStatus] = useState("");

  async function save() {
    const res = await fetch("/api/admin/friction", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ toggles, note }),
    });
    if (res.ok) {
      setStatus("Saved. Changes apply immediately.");
      setNote("");
    } else setStatus("Save failed.");
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="font-serif text-3xl font-bold">Friction toggles</h1>
        <p className="text-sm text-stone-500">Each change is recorded as a config_change event in the access log.</p>
      </div>
      <ul className="divide-y divide-stone-200 rounded border border-stone-200 bg-white">
        {FRICTION_IDS.map((id) => (
          <li key={id} className="flex items-start gap-3 p-3">
            <input id={`t-${id}`} type="checkbox" checked={toggles[id]} data-testid={`toggle-${id}`}
              onChange={(e) => setToggles({ ...toggles, [id]: e.target.checked })} className="mt-1 h-4 w-4" />
            <label htmlFor={`t-${id}`} className="text-sm">
              <span className="font-mono font-semibold">{id}</span> {FRICTION_LABELS[id].label}
              <span className="block text-stone-500">{FRICTION_LABELS[id].description}</span>
            </label>
          </li>
        ))}
      </ul>
      <label className="block text-sm font-medium">Annotation note (stored with the change)
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={280} data-testid="admin-note"
          placeholder="e.g. Removed pincode wall (F05)" className="mt-1 w-full rounded border border-stone-300 px-3 py-2 font-normal" />
      </label>
      <div className="flex items-center gap-4">
        <button type="button" onClick={save} data-testid="admin-save" className="rounded bg-rust-700 px-6 py-2 font-semibold text-white">Save</button>
        {status && <span role="status" className="text-sm text-stone-600">{status}</span>}
      </div>
    </div>
  );
}
