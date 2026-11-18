import { NextResponse } from "next/server";
import { getCategory, getProductBySlug, productsInCategory } from "../../../lib/catalog";
import { productSvg, sizeChartSvg } from "../../../lib/svg";

const svg = (body: string) =>
  new NextResponse(body, {
    headers: { "Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=3600" },
  });

export async function GET(_req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const [kind, file = ""] = path;
  const name = file.replace(/\.svg$/, "");

  if (kind === "p") {
    const m = /^(.*)-(\d)$/.exec(name);
    const product = m ? getProductBySlug(m[1]) : undefined;
    if (product && m) return svg(productSvg(product, Number(m[2])));
  }
  if (kind === "size") {
    const cat = getCategory(name);
    const first = cat ? productsInCategory(cat.slug)[0] : undefined;
    if (cat && first) return svg(sizeChartSvg(`${cat.name} size chart`, first.size_chart.html));
  }
  return new NextResponse("Not found", { status: 404 });
}
