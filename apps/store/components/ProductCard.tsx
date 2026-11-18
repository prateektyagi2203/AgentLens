import type { Product } from "../lib/catalog";
import { formatINR } from "../lib/format";
import SLink from "./SLink";

export default function ProductCard({ product }: { product: Product }) {
  return (
    <SLink
      href={`/p/${product.slug}`}
      className="group block overflow-hidden rounded-lg border border-stone-200 bg-white transition hover:shadow-md"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={product.images[0]} alt={product.name} width={600} height={750} className="aspect-[4/5] w-full object-cover" />
      <div className="p-3">
        <h3 className="line-clamp-2 text-sm font-medium text-stone-800 group-hover:text-rust-700">{product.name}</h3>
        <p className="mt-1 text-xs text-stone-500">{product.rating.value} ★ ({product.rating.count})</p>
        <p className="mt-1 text-sm">
          <span className="font-semibold text-stone-900">{formatINR(product.price)}</span>{" "}
          <span className="text-stone-400 line-through">{formatINR(product.mrp)}</span>{" "}
          <span className="text-xs text-green-700">{product.discount_pct}% off</span>
        </p>
      </div>
    </SLink>
  );
}
