import { notFound } from "next/navigation";
import { getCategory } from "../../../lib/catalog";
import { readToggles, sizeGuideMode } from "../../../lib/friction";
import { loadCatalog } from "../../../lib/catalog";

export default async function SizeGuide({ params }: { params: Promise<{ category: string }> }) {
  const slug = (await params).category;
  const cat = getCategory(slug);
  if (!cat) notFound();
  const mode = sizeGuideMode(readToggles());
  const sample = loadCatalog().products.find((p) => p.category === cat.slug)!;

  return (
    <div className="space-y-6">
      <h1 className="font-serif text-3xl font-bold">Size guide: {cat.name}</h1>
      {mode === "table-and-image" && (
        <div data-testid="size-table" className="overflow-x-auto rounded border border-stone-200 bg-white p-4 text-sm
          [&_table]:w-full [&_td]:border [&_td]:border-stone-200 [&_td]:px-3 [&_td]:py-2 [&_th]:border [&_th]:border-stone-200 [&_th]:bg-stone-100 [&_th]:px-3 [&_th]:py-2"
          dangerouslySetInnerHTML={{ __html: sample.size_chart.html }} />
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`/img/size/${cat.slug}.svg`} alt={`${cat.name} size chart`} width={800} height={500} className="max-w-full rounded border border-stone-200" />
    </div>
  );
}
