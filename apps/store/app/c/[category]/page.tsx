import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ProductGrid from "../../../components/ProductGrid";
import { getCategory, productsInCategory } from "../../../lib/catalog";

type Params = { params: Promise<{ category: string }>; searchParams: Promise<{ sort?: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const cat = getCategory((await params).category);
  return { title: cat ? `${cat.name} | Desi Threads (TEST STORE)` : "Not found" };
}

export default async function CategoryPage({ params, searchParams }: Params) {
  const cat = getCategory((await params).category);
  if (!cat) notFound();
  const { sort } = await searchParams;
  const products = [...productsInCategory(cat.slug)];
  if (sort === "price-asc") products.sort((a, b) => a.price - b.price);
  if (sort === "price-desc") products.sort((a, b) => b.price - a.price);

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="font-serif text-3xl font-bold">{cat.name}</h1>
          <p className="text-sm text-stone-500">{products.length} products</p>
        </div>
        <form method="get" className="text-sm">
          <label className="mr-2 text-stone-600" htmlFor="sort">Sort by</label>
          <select id="sort" name="sort" defaultValue={sort ?? ""} className="rounded border border-stone-300 px-2 py-1">
            <option value="">Featured</option>
            <option value="price-asc">Price: low to high</option>
            <option value="price-desc">Price: high to low</option>
          </select>
          <button type="submit" className="ml-2 rounded border border-stone-300 px-2 py-1">Apply</button>
        </form>
      </div>
      <ProductGrid products={products} />
    </div>
  );
}
