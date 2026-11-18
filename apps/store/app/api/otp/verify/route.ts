import { apiContext, apiError, jsonResponse, readJson, str } from "../../../../lib/api";
import { DEV_OTP } from "../../../../lib/friction";

export async function POST(req: Request) {
  const { state } = apiContext(req);
  const body = await readJson(req);
  if (str(body.otp) !== DEV_OTP) return apiError(req, 400, "OTP_INVALID", { message: "Incorrect OTP" });
  if (str(body.purpose) === "cod") state.codOtpVerified = true;
  else state.otpVerified = true;
  return jsonResponse(req, 200, { verified: true });
}
