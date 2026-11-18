import { isAdminRequest, adminEnabled } from "../../../../lib/admin";
import { apiError, jsonResponse, logExtraEvent, readJson, str } from "../../../../lib/api";
import { FRICTION_IDS, readToggles, writeToggles, type FrictionId } from "../../../../lib/friction";

function guard(req: Request) {
  if (!adminEnabled()) return apiError(req, 404, "NOT_FOUND");
  if (!isAdminRequest(req.headers)) return apiError(req, 401, "ADMIN_AUTH");
  return null;
}

export async function GET(req: Request) {
  const denied = guard(req);
  if (denied) return denied;
  return jsonResponse(req, 200, { toggles: readToggles() });
}

/** Body: { toggles: { F05: false, ... }, note?: string }. Unknown ids are ignored; omitted ids are unchanged. */
export async function POST(req: Request) {
  const denied = guard(req);
  if (denied) return denied;
  const body = await readJson(req);
  const incoming = (body.toggles && typeof body.toggles === "object" ? body.toggles : {}) as Record<string, unknown>;
  const patch: Partial<Record<FrictionId, boolean>> = {};
  for (const id of FRICTION_IDS) if (typeof incoming[id] === "boolean") patch[id] = incoming[id] as boolean;

  const { toggles, changed } = writeToggles(patch);
  const note = str(body.note).trim().slice(0, 280);
  if (changed.length > 0 || note) {
    logExtraEvent(req, "config_change", { toggles, changed, ...(note ? { note } : {}) }, 200);
  }
  return jsonResponse(req, 200, { toggles, changed });
}
