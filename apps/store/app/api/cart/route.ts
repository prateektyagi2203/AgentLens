import { apiContext, apiError, jsonResponse, readJson, str } from "../../../lib/api";
import { getProductById, getProductBySlug } from "../../../lib/catalog";
import { cartGuard, cartUnitPrice, readToggles } from "../../../lib/friction";
import { cartValue } from "../../../lib/state";

export async function GET(req: Request) {
  const { state } = apiContext(req);
  return jsonResponse(req, 200, { items: state.cart, cart_value: cartValue(state) });
}

export async function POST(req: Request) {
  const { state } = apiContext(req);
  const toggles = readToggles();

  const rejection = cartGuard(toggles, state);
  if (rejection) {
    const { error_code, status, ...extra } = rejection;
    return apiError(req, status, error_code, extra);
  }

  const body = await readJson(req);
  const productRef = str(body.product_id) || str(body.slug);
  const product = getProductById(productRef) ?? getProductBySlug(productRef);
  if (!product) return apiError(req, 404, "PRODUCT_NOT_FOUND");

  const size = str(body.size).toLowerCase();
  const colour = str(body.colour).toLowerCase();
  const matches = product.variants.filter(
    (v) => (!size || v.size.toLowerCase() === size) && (!colour || v.colour.toLowerCase() === colour),
  );
  if (matches.length !== 1) return apiError(req, 422, "VARIANT_REQUIRED", { message: "Choose a size and colour" });
  const variant = matches[0];

  const qty = Math.min(5, Math.max(1, Math.floor(Number(body.qty ?? 1)) || 1));
  if (variant.stock < qty) return apiError(req, 409, "OUT_OF_STOCK", { message: "This item is out of stock" });

  const unitPrice = cartUnitPrice(toggles, product);
  const existing = state.cart.find((i) => i.product_id === product.id && i.size === variant.size && i.colour === variant.colour);
  if (existing) {
    existing.qty += qty;
    existing.unit_price = unitPrice;
  } else {
    state.cart.push({
      product_id: product.id,
      slug: product.slug,
      name: product.name,
      size: variant.size,
      colour: variant.colour,
      qty,
      unit_price: unitPrice,
    });
  }
  const result = { product_id: product.id, unit_price: unitPrice, qty, cart_value: cartValue(state) };
  return jsonResponse(req, 201, result, result);
}
