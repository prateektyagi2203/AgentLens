import { apiContext, apiError, jsonResponse } from "../../../lib/api";

const VALID_PINCODE = /^[1-9]\d{5}$/;

export async function GET(req: Request) {
  const { state } = apiContext(req);
  const pincode = new URL(req.url).searchParams.get("pincode") ?? "";

  // Pincodes starting with 9 stand in for areas we do not deliver to.
  if (!VALID_PINCODE.test(pincode) || pincode.startsWith("9")) {
    return apiError(req, 422, "PINCODE_UNSERVICEABLE", { serviceable: false });
  }
  state.pincodeOk = true;
  const etaDays = 2 + (Number(pincode.slice(-2)) % 4);
  return jsonResponse(
    req,
    200,
    { serviceable: true, pincode, eta_days: etaDays, cod_available: true },
    { serviceable: true },
  );
}
