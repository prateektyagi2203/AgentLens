import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { apiContext, apiError, jsonResponse, logExtraEvent, readJson, str } from "../../../lib/api";
import { hashSid } from "../../../lib/client";
import { captchaRequired, codOtpRequired, DEV_OTP, phoneValid, readToggles } from "../../../lib/friction";
import { envSalt } from "../../../lib/logger";
import { ordersFile } from "../../../lib/paths";
import { cartValue, registry } from "../../../lib/state";

const METHODS = new Set(["COD", "UPI", "CARD"]);

export async function POST(req: Request) {
  const { state, clientKey } = apiContext(req);
  const toggles = readToggles();
  const body = await readJson(req);

  if (state.cart.length === 0) return apiError(req, 409, "CART_EMPTY", { message: "Your cart is empty" });

  const solved =
    state.captchaAnswer !== null && str(body.captcha_answer).trim().toUpperCase() === state.captchaAnswer;
  if (captchaRequired(toggles, solved)) {
    return apiError(req, 403, "CAPTCHA_REQUIRED", { message: "Please solve the captcha" });
  }

  if (!phoneValid(toggles, body.phone)) return apiError(req, 422, "PHONE_FORMAT", { message: "Invalid phone number" });

  const method = str(body.payment_method).toUpperCase();
  if (!str(body.name).trim() || !str(body.address).trim() || !METHODS.has(method)) {
    return apiError(req, 422, "FIELD_REQUIRED", { message: "Name, address and payment method are required" });
  }

  const codVerified = state.codOtpVerified || str(body.cod_otp) === DEV_OTP;
  if (codOtpRequired(toggles, method, codVerified)) {
    return apiError(req, 409, "COD_OTP_REQUIRED", { message: "Confirm your COD order with the OTP sent to your phone" });
  }

  const orderId = `DT-${crypto.randomBytes(4).toString("hex").toUpperCase()}`;
  const value = cartValue(state);
  const ts = new Date().toISOString();
  const sessionId = hashSid(clientKey.replace(/^sid:/, ""), envSalt());

  fs.mkdirSync(path.dirname(ordersFile()), { recursive: true });
  fs.appendFileSync(
    ordersFile(),
    JSON.stringify({ order_id: orderId, session_cookie_id: sessionId, cart_value: value, ts, payment_method: method }) + "\n",
  );
  registry().orders.set(orderId, { order_id: orderId, cart_value: value, payment_method: method, ts, items: [...state.cart] });

  state.cart = [];
  state.captchaAnswer = null;
  state.codOtpVerified = false;

  const result = { order_id: orderId, cart_value: value, payment_method: method };
  logExtraEvent(req, "order", result, 201);
  return jsonResponse(req, 201, result, result);
}
