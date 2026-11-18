export interface CartItem {
  product_id: string;
  slug: string;
  name: string;
  size: string;
  colour: string;
  qty: number;
  unit_price: number;
}

export interface ClientState {
  pincodeOk: boolean;
  otpVerified: boolean;
  codOtpVerified: boolean;
  /** Expected captcha answer for the most recent /api/captcha challenge. */
  captchaAnswer: string | null;
  cart: CartItem[];
  touched: number;
}

export interface MetaEntry {
  meta?: Record<string, unknown>;
  eventType?: "request" | "beacon";
}

export interface OrderRecord {
  order_id: string;
  cart_value: number;
  payment_method: string;
  ts: string;
  items: CartItem[];
}

interface Registry {
  states: Map<string, ClientState>;
  /** A freshly issued dt_sid points at the ip+ua state the cookie-less client already built up. */
  aliases: Map<string, string>;
  meta: Map<string, MetaEntry>;
  orders: Map<string, OrderRecord>;
  frictionCache: { key: string; toggles: unknown } | null;
}

// The custom server (tsx) and the Next.js bundle load separate module copies, so shared state lives on globalThis.
const g = globalThis as unknown as { __agentlens?: Registry };

export function registry(): Registry {
  if (!g.__agentlens) {
    g.__agentlens = { states: new Map(), aliases: new Map(), meta: new Map(), orders: new Map(), frictionCache: null };
  }
  return g.__agentlens;
}

const MAX_STATES = 5000;

export function aliasSid(sidKey: string, targetKey: string): void {
  const { aliases } = registry();
  if (aliases.size >= MAX_STATES) {
    const oldest = aliases.keys().next().value;
    if (oldest !== undefined) aliases.delete(oldest);
  }
  aliases.set(sidKey, targetKey);
}

export function getState(requestedKey: string): ClientState {
  const { states, aliases } = registry();
  const key = !states.has(requestedKey) ? (aliases.get(requestedKey) ?? requestedKey) : requestedKey;
  let s = states.get(key);
  if (!s) {
    if (states.size >= MAX_STATES) {
      const oldest = states.keys().next().value;
      if (oldest !== undefined) states.delete(oldest);
    }
    s = { pincodeOk: false, otpVerified: false, codOtpVerified: false, captchaAnswer: null, cart: [], touched: 0 };
    states.set(key, s);
  }
  s.touched = Date.now();
  return s;
}

export function cartValue(s: ClientState): number {
  return s.cart.reduce((n, i) => n + i.unit_price * i.qty, 0);
}

/** Route handlers register meta for the request logger (looked up by request id when the response closes). */
export function setRequestMeta(requestId: string | null | undefined, entry: MetaEntry): void {
  if (!requestId) return;
  const { meta } = registry();
  const prev = meta.get(requestId);
  meta.set(requestId, { ...prev, ...entry, meta: { ...prev?.meta, ...entry.meta } });
}

export function takeRequestMeta(requestId: string): MetaEntry | undefined {
  const { meta } = registry();
  const e = meta.get(requestId);
  meta.delete(requestId);
  return e;
}
