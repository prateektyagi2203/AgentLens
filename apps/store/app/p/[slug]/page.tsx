import type { Metadata } from "next";
import { notFound } from "next/navigation";
import PdpPurchase from "../../../components/PdpPurchase";
import SLink from "../../../components/SLink";
import { getCategory, getProductBySlug, similarProducts, totalStock, type Product } from "../../../lib/catalog";
import { formatINR } from "../../../lib/format";
import { overlays, pdpRender, readToggles } from "../../../lib/friction";
import { pageContext } from "../../../lib/page-context";

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const product = getProductBySlug((await params).slug);
  return { title: product ? `${product.name} | Desi Threads (TEST STORE)` : "Not found" };
}

function jsonLd(product: Product, mode: "basic" | "full", origin: string) {
  const base: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: product.name,
    description: product.description,
    sku: product.id,
    brand: { "@type": "Brand", name: product.brand },
    image: product.images.map((i) => `${origin}${i}`),
    url: `${origin}/p/${product.slug}`,
  };
  if (mode === "basic") return base;
  const inStock = totalStock(product) > 0;
  const availability = (stock: number) => (stock > 0 ? "https://schema.org/InStock" : "https://schema.org/OutOfStock");
  return {
    ...base,
    aggregateRating: { "@type": "AggregateRating", ratingValue: product.rating.value, reviewCount: product.rating.count },
    offers: {
      "@type": "Offer",
      price: product.price,
      priceCurrency: "INR",
      availability: availability(inStock ? 1 : 0),
      url: `${origin}/p/${product.slug}`,
    },
    hasVariant: product.variants.map((v) => ({
      "@type": "Product",
      sku: v.sku,
      size: v.size,
      color: v.colour,
      offers: { "@type": "Offer", price: product.price, priceCurrency: "INR", availability: availability(v.stock) },
    })),
  };
}

export default async function ProductPage({ params }: Params) {
  const product = getProductBySlug((await params).slug);
  if (!product) notFound();

  const toggles = readToggles();
  const render = pdpRender(toggles);
  const ov = overlays(toggles);
  const { state, origin } = await pageContext();
  const category = getCategory(product.category);
  const sizes = [...new Set(product.variants.map((v) => v.size))];
  const colours = [...new Set(product.variants.map((v) => v.colour))];
  const inStock = totalStock(product) > 0;
  const related = similarProducts(product);

  return (
    <article className="grid gap-8 md:grid-cols-2">
      {render.jsonLd !== "none" && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify(jsonLd(product, render.jsonLd, origin)).replace(/</g, "\\u003c"),
          }}
        />
      )}

      <div className="grid grid-cols-2 gap-2">
        {product.images.map((src, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={src} src={src} alt={`${product.name} view ${i + 1}`} width={600} height={750}
            className={`w-full rounded-lg border border-stone-200 object-cover ${i === 0 ? "col-span-2" : ""}`} />
        ))}
      </div>

      <div className="space-y-5">
        <nav aria-label="Breadcrumb" className="text-xs text-stone-500">
          <SLink href="/" className="hover:underline">Home</SLink> /{" "}
          <SLink href={`/c/${product.category}`} className="hover:underline">{category?.name}</SLink>
        </nav>
        <div>
          <p className="text-sm uppercase tracking-wide text-stone-500">{product.brand}</p>
          <h1 className="font-serif text-3xl font-bold">{product.name}</h1>
          <p className="mt-1 text-sm text-stone-600">{product.rating.value} ★ ({product.rating.count} reviews)</p>
        </div>

        {render.priceInHtml && (
          <div>
            <p className="text-2xl font-semibold" data-testid="price">
              {formatINR(product.price)}{" "}
              <span className="text-base font-normal text-stone-400 line-through">{formatINR(product.mrp)}</span>{" "}
              <span className="text-base font-normal text-green-700">{product.discount_pct}% off</span>
            </p>
            <p className="mt-1 text-sm" data-testid="stock">
              {inStock ? <span className="text-green-700">In stock</span> : <span className="text-red-700">Out of stock</span>}
            </p>
          </div>
        )}

        <PdpPurchase
          product={{
            id: product.id,
            slug: product.slug,
            sizes,
            colours,
            variants: render.priceInHtml ? product.variants : null,
          }}
          serverPrice={render.priceInHtml}
          initialPincodeOk={state.pincodeOk}
          pincodeModal={ov.pincodeModal}
          appInterstitial={ov.appInterstitial}
          closeDelayMs={ov.closeDelayMs}
        />

        <section className="space-y-2 border-t border-stone-200 pt-4 text-sm text-stone-700">
          <p>{product.description}</p>
          <ul className="list-disc pl-5">
            <li>Material: {product.attributes.material}</li>
            <li>Fit: {product.attributes.fit}</li>
            <li>Colour: {product.attributes.colour}</li>
          </ul>
          <p>
            <SLink href={`/size-guide/${product.category}`} className="text-rust-700 underline">Size guide</SLink>
            {" · "}
            <SLink href="/policies/returns" className="text-rust-700 underline">
              {product.return_policy.window_days}-day returns
            </SLink>
          </p>
          <p className="text-stone-500">{product.return_policy.text}</p>
        </section>
      </div>

      {related.length > 0 && (
        <section className="md:col-span-2">
          <h2 className="mb-3 font-serif text-xl font-bold">You may also like</h2>
          <ul className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {related.map((r) => (
              <li key={r.id}>
                <SLink href={`/p/${r.slug}`} className="block rounded border border-stone-200 bg-white p-3 text-sm hover:text-rust-700">
                  {r.name}
                </SLink>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
