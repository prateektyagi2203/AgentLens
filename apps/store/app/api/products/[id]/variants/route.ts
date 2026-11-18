import { getProductById, getProductBySlug, similarProducts } from "../../../../../lib/catalog";
import { oosPolicy, readToggles } from "../../../../../lib/friction";
import { apiError, jsonResponse } from "../../../../../lib/api";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const product = getProductById(id) ?? getProductBySlug(id);
  if (!product) return apiError(req, 404, "PRODUCT_NOT_FOUND");

  const url = new URL(req.url);
  const size = url.searchParams.get("size");
  const colour = url.searchParams.get("colour") ?? url.searchParams.get("color");

  if (!size && !colour) {
    return jsonResponse(req, 200, {
      product_id: product.id,
      price: product.price,
      mrp: product.mrp,
      currency: "INR",
      variants: product.variants.map((v) => ({ ...v, available: v.stock > 0 })),
    });
  }

  const variant = product.variants.find(
    (v) =>
      (!size || v.size.toLowerCase() === size.toLowerCase()) &&
      (!colour || v.colour.toLowerCase() === colour.toLowerCase()),
  );
  if (!variant) return apiError(req, 404, "VARIANT_NOT_FOUND");

  if (variant.stock > 0) {
    return jsonResponse(req, 200, { product_id: product.id, available: true, variant, price: product.price });
  }

  const policy = oosPolicy(readToggles());
  if (!policy.alternatives) {
    return apiError(req, policy.status, "OUT_OF_STOCK", { message: "This item is out of stock" });
  }
  return jsonResponse(req, policy.status, {
    product_id: product.id,
    available: false,
    variant,
    alternatives: {
      variants: product.variants.filter((v) => v.stock > 0),
      similar_products: similarProducts(product).map((p) => ({ id: p.id, slug: p.slug, name: p.name, price: p.price })),
    },
  });
}
