import ProductGrid from "../../components/ProductGrid";
import { searchProducts } from "../../lib/catalog";

export const metadata = { title: "Search | Desi Threads (TEST STORE)" };

export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const q = ((await searchParams).q ?? "").trim().slice(0, 100);
  const results = searchProducts(q);
  return (
    <div>
      <h1 className="font-serif text-3xl font-bold">{q ? `Results for "${q}"` : "Search"}</h1>
      <p className="mb-6 text-sm text-stone-500">{q ? `${results.length} products` : "Type something in the search box."}</p>
      <ProductGrid products={results} />
    </div>
  );
}
