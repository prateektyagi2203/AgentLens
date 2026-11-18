import fs from "node:fs";
import { catalogFile } from "./paths";

export type CategorySlug = "mens-sneakers" | "womens-kurtas" | "mens-shirts" | "accessories";

export interface Category {
  slug: CategorySlug;
  name: string;
}

export interface Variant {
  sku: string;
  size: string;
  colour: string;
  stock: number;
}

export interface Product {
  id: string;
  slug: string;
  name: string;
  brand: string;
  category: CategorySlug;
  price: number;
  mrp: number;
  discount_pct: number;
  images: string[];
  description: string;
  attributes: { material: string; fit: string; colour: string };
  variants: Variant[];
  size_chart: { html: string; image: string };
  return_policy: { window_days: number; text: string };
  rating: { value: number; count: number };
  /** True for the two products whose cart price differs from the PDP price when F11 is on. */
  price_mismatch: boolean;
  cart_price: number | null;
}

export interface Catalog {
  generated_by: string;
  seed: number;
  currency: "INR";
  categories: Category[];
  products: Product[];
}

let cache: { mtimeMs: number; catalog: Catalog } | null = null;

export function loadCatalog(): Catalog {
  const file = catalogFile();
  const mtimeMs = fs.statSync(file).mtimeMs;
  if (cache && cache.mtimeMs === mtimeMs) return cache.catalog;
  const catalog = JSON.parse(fs.readFileSync(file, "utf8")) as Catalog;
  cache = { mtimeMs, catalog };
  return catalog;
}

export const getProductBySlug = (slug: string) => loadCatalog().products.find((p) => p.slug === slug);
export const getProductById = (id: string) => loadCatalog().products.find((p) => p.id === id);
export const getCategory = (slug: string) => loadCatalog().categories.find((c) => c.slug === slug);
export const productsInCategory = (slug: string) => loadCatalog().products.filter((p) => p.category === slug);

export function searchProducts(q: string): Product[] {
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const { products, categories } = loadCatalog();
  return products.filter((p) => {
    const cat = categories.find((c) => c.slug === p.category)?.name ?? "";
    const hay = [p.name, cat, p.attributes.material, p.attributes.colour, p.description].join(" ").toLowerCase();
    return terms.every((t) => hay.includes(t));
  });
}

export function totalStock(p: Product): number {
  return p.variants.reduce((n, v) => n + v.stock, 0);
}

export function productUrl(p: Pick<Product, "slug">): string {
  return `/p/${p.slug}`;
}

export function similarProducts(p: Product, limit = 4): Product[] {
  return productsInCategory(p.category)
    .filter((o) => o.id !== p.id && totalStock(o) > 0)
    .slice(0, limit);
}
