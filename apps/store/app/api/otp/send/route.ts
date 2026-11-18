import { apiError, jsonResponse, readJson, str } from "../../../../lib/api";

export async function POST(req: Request) {
  const body = await readJson(req);
  const digits = str(body.phone).replace(/\D/g, "");
  if (digits.length < 10) return apiError(req, 422, "PHONE_FORMAT", { message: "Invalid phone number" });
  // The SMS is simulated: nothing is sent and neither the number nor the code is logged.
  return jsonResponse(req, 200, { sent: true, purpose: str(body.purpose) || "login" });
}
