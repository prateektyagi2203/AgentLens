import { productsInCategory, loadCatalog } from "../lib/catalog";
import { readToggles } from "../lib/friction";
import { SpinWheel } from "../components/Overlays";
import ProductGrid from "../components/ProductGrid";
import SLink from "../components/SLink";

const TILES = [
  { slug: "mens-sneakers", label: "Men's sneakers", tone: "from-stone-700 to-stone-900" },
  { slug: "womens-kurtas", label: "Women's kurtas", tone: "from-rust-600 to-rust-800" },
  { slug: "mens-shirts", label: "Men's shirts", tone: "from-teal-700 to-teal-900" },
  { slug: "accessories", label: "Accessories", tone: "from-amber-600 to-amber-800" },
];

export default function Home() {
  const featured = loadCatalog().products.filter((_, i) => i % 4 === 0).slice(0, 8);
  const spin = readToggles().F08;
  return (
    <div className="space-y-12">
      {spin && <SpinWheel />}
      <section className="rounded-2xl bg-gradient-to-r from-rust-700 to-rust-600 px-8 py-14 text-white">
        <p className="text-sm uppercase tracking-widest text-white/80">New season</p>
        <h1 className="mt-2 font-serif text-4xl font-bold md:text-5xl">Everyday Indian wear, made to last</h1>
        <p className="mt-3 max-w-xl text-white/90">Kurtas, shirts, sneakers and accessories with easy 15-day returns.</p>
        <SLink href="/c/womens-kurtas" className="mt-6 inline-block rounded-full bg-white px-6 py-2 font-semibold text-rust-800">
          Shop kurtas
        </SLink>
      </section>

      <section aria-label="Shop by category" className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {TILES.map((t) => (
          <SLink key={t.slug} href={`/c/${t.slug}`}
            className={`flex h-32 items-end rounded-xl bg-gradient-to-br ${t.tone} p-4 font-serif text-lg font-semibold text-white`}>
            {t.label} <span className="ml-2 text-xs font-normal opacity-80">({productsInCategory(t.slug).length})</span>
          </SLink>
        ))}
      </section>

      <section>
        <h2 className="mb-4 font-serif text-2xl font-bold">Bestsellers</h2>
        <ProductGrid products={featured} />
      </section>
    </div>
  );
}
