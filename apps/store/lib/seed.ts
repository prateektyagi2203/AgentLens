import type { Catalog, CategorySlug, Product, Variant } from "./catalog";

export const CATALOG_SEED = 20261118;

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const CATEGORIES = [
  { slug: "mens-sneakers", name: "Men's sneakers" },
  { slug: "womens-kurtas", name: "Women's kurtas" },
  { slug: "mens-shirts", name: "Men's shirts" },
  { slug: "accessories", name: "Accessories" },
] as const;

const COLOURS = [
  "White", "Black", "Navy", "Olive", "Maroon", "Mustard", "Teal", "Pink", "Indigo", "Grey", "Tan", "Sky Blue",
];

interface CategorySpec {
  prefix: string;
  names: string[];
  sizes: string[][];
  materials: string[];
  fits: string[];
  priceRange: [number, number];
  blurb: string;
  chart: { head: string[]; rows: string[][] };
}

const SPECS: Record<CategorySlug, CategorySpec> = {
  "mens-sneakers": {
    prefix: "SNK",
    names: [
      "Court Sneaker", "Street Runner", "Classic Canvas Low", "Retro Trainer", "Everyday Slip-On",
      "Urban High-Top", "Sprint Knit Runner", "Heritage Leather Sneaker", "Pace Lite Trainer", "Terrain Trail Sneaker",
      "Metro Mesh Sneaker", "Studio Court Low", "Daily Walk Sneaker", "Fleet Foam Runner", "Alley Suede Sneaker",
    ],
    sizes: [["UK 6", "UK 7", "UK 8", "UK 9", "UK 10", "UK 11"]],
    materials: ["Recycled mesh", "Full-grain leather", "Cotton canvas", "Suede", "Knit upper"],
    fits: ["Regular", "Wide", "Snug"],
    priceRange: [1799, 4999],
    blurb: "Cushioned insole, durable rubber outsole and a clean silhouette that pairs with everything from chinos to shorts.",
    chart: {
      head: ["UK size", "EU size", "Foot length (cm)"],
      rows: [["UK 6", "40", "24.5"], ["UK 7", "41", "25.4"], ["UK 8", "42", "26.2"], ["UK 9", "43", "27.1"], ["UK 10", "44", "27.9"], ["UK 11", "45", "28.8"]],
    },
  },
  "womens-kurtas": {
    prefix: "KRT",
    names: [
      "Block Print Straight Kurta", "Chikankari Anarkali Kurta", "Cotton A-Line Kurta", "Bandhani Flared Kurta",
      "Festive Embroidered Kurta", "Daily Wear Pintuck Kurta", "Jaipur Print Long Kurta", "Rayon Kaftan Kurta",
      "Handloom Yoke Kurta", "Ikat Print Kurta", "Mirror Work Short Kurta", "Linen Mandarin Kurta",
      "Gotta Patti Kurta", "Floral Dobby Kurta", "Pleated Asymmetric Kurta",
    ],
    sizes: [["XS", "S", "M", "L", "XL", "XXL"]],
    materials: ["Cotton", "Rayon", "Linen blend", "Chanderi silk blend", "Mulmul cotton"],
    fits: ["Straight", "A-line", "Relaxed"],
    priceRange: [899, 2999],
    blurb: "Breathable fabric with fine detailing, cut for an easy drape that works from office to festive evenings.",
    chart: {
      head: ["Size", "Bust (in)", "Waist (in)", "Length (in)"],
      rows: [["XS", "32", "28", "44"], ["S", "34", "30", "44"], ["M", "36", "32", "45"], ["L", "38", "34", "45"], ["XL", "40", "36", "46"], ["XXL", "42", "38", "46"]],
    },
  },
  "mens-shirts": {
    prefix: "SHT",
    names: [
      "Oxford Button-Down Shirt", "Linen Casual Shirt", "Checked Flannel Shirt", "Mandarin Collar Shirt",
      "Printed Resort Shirt", "Classic Formal Shirt", "Denim Overshirt", "Striped Cotton Shirt",
      "Chambray Work Shirt", "Textured Dobby Shirt", "Kurta-Style Shirt", "Half-Sleeve Linen Shirt",
      "Cuban Collar Shirt", "Poplin Slim Shirt", "Seersucker Weekend Shirt",
    ],
    sizes: [["S", "M", "L", "XL", "XXL"]],
    materials: ["Cotton poplin", "Linen", "Oxford cotton", "Brushed flannel", "Chambray"],
    fits: ["Slim", "Regular", "Relaxed"],
    priceRange: [799, 2299],
    blurb: "Easy-care fabric with a structured collar and a tailored cut; machine washable.",
    chart: {
      head: ["Size", "Chest (in)", "Shoulder (in)", "Length (in)"],
      rows: [["S", "38", "17", "27.5"], ["M", "40", "17.5", "28"], ["L", "42", "18", "28.5"], ["XL", "44", "18.5", "29"], ["XXL", "46", "19", "29.5"]],
    },
  },
  accessories: {
    prefix: "ACC",
    names: [
      "Leather Belt", "Bifold Wallet", "Canvas Tote Bag", "Baseball Cap", "Aviator Sunglasses",
      "Woven Cotton Scarf", "Minimal Analog Watch", "Sling Crossbody Bag", "Beanie", "Card Holder",
      "Printed Pocket Square", "Leather Watch Strap", "Everyday Backpack", "Ankle Socks Pack", "Reversible Belt",
    ],
    sizes: [["Free Size"], ["30", "32", "34", "36", "38"]],
    materials: ["Genuine leather", "Cotton canvas", "Recycled polyester", "Stainless steel", "Wool blend"],
    fits: ["Standard"],
    priceRange: [399, 1499],
    blurb: "A small everyday essential, finished with durable hardware and stitching.",
    chart: {
      head: ["Waist (in)", "Belt size"],
      rows: [["28-30", "30"], ["30-32", "32"], ["32-34", "34"], ["34-36", "36"], ["36-38", "38"]],
    },
  },
};

const slugify = (s: string) =>
  s.toLowerCase().replace(/['’]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

function chartHtml(spec: CategorySpec): string {
  const head = spec.chart.head.map((h) => `<th>${h}</th>`).join("");
  const rows = spec.chart.rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("");
  return `<table class="size-chart"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
}

export function generateCatalog(seed: number = CATALOG_SEED): Catalog {
  const rnd = mulberry32(seed);
  const pick = <T>(arr: readonly T[]): T => arr[Math.floor(rnd() * arr.length)];
  const int = (lo: number, hi: number) => lo + Math.floor(rnd() * (hi - lo + 1));

  const products: Product[] = [];
  const usedSlugs = new Set<string>();

  for (const cat of CATEGORIES) {
    const spec = SPECS[cat.slug];
    spec.names.forEach((base, i) => {
      const colourCount = int(2, 3);
      const colours: string[] = [];
      while (colours.length < colourCount) {
        const c = pick(COLOURS);
        if (!colours.includes(c)) colours.push(c);
      }
      const primary = colours[0];
      const name = cat.slug === "mens-sneakers" || cat.slug === "mens-shirts" ? `${primary} ${base}` : `${base} in ${primary}`;
      let slug = slugify(name);
      if (usedSlugs.has(slug)) slug = `${slug}-${i + 1}`;
      usedSlugs.add(slug);

      const sizes = spec.sizes.length > 1 && /Belt/.test(base) ? spec.sizes[1] : spec.sizes[0];
      const id = `${spec.prefix}${String(i + 1).padStart(3, "0")}`;
      const variants: Variant[] = [];
      for (const colour of colours) {
        for (const size of sizes) {
          variants.push({
            sku: `${id}-${slugify(size).toUpperCase()}-${slugify(colour).toUpperCase()}`,
            size,
            colour,
            stock: int(3, 40),
          });
        }
      }

      const mrp = Math.round(int(spec.priceRange[0] + 200, spec.priceRange[1] + 700) / 100) * 100 - 1;
      const discountTarget = int(15, 45);
      const price = Math.round((mrp * (100 - discountTarget)) / 100 / 10) * 10 - 1;
      const material = pick(spec.materials);

      products.push({
        id,
        slug,
        name,
        brand: "Desi Threads",
        category: cat.slug,
        price,
        mrp,
        discount_pct: Math.round(((mrp - price) / mrp) * 100),
        images: [1, 2, 3].map((n) => `/img/p/${slug}-${n}.svg`),
        description: `${name} from Desi Threads. Made with ${material.toLowerCase()}. ${spec.blurb}`,
        attributes: { material, fit: pick(spec.fits), colour: primary },
        variants,
        size_chart: { html: chartHtml(spec), image: `/img/size/${cat.slug}.svg` },
        return_policy: {
          window_days: cat.slug === "accessories" ? 7 : 15,
          text:
            cat.slug === "accessories"
              ? "7-day exchange for unused accessories in original packaging."
              : "15-day easy returns for unworn items with tags intact. Free pickup on prepaid orders.",
        },
        rating: { value: Math.round((3.6 + rnd() * 1.2) * 10) / 10, count: int(12, 940) },
        price_mismatch: false,
        cart_price: null,
      });
    });
  }

  // Exactly 10% of variants are out of stock; every product keeps at least one in-stock variant.
  const all = products.flatMap((p) => p.variants.map((v) => ({ p, v })));
  const target = Math.round(all.length * 0.1);
  const order = all.map((_, i) => i);
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [order[i], order[j]] = [order[j], order[i]];
  }
  let oos = 0;
  for (const idx of order) {
    if (oos >= target) break;
    const { p, v } = all[idx];
    if (p.variants.filter((x) => x.stock > 0).length <= 1) continue;
    v.stock = 0;
    oos++;
  }

  // Two price-mismatch products (one sneaker, one shirt), fixed by the seed.
  const mismatchPool = [
    products.filter((p) => p.category === "mens-sneakers"),
    products.filter((p) => p.category === "mens-shirts"),
  ];
  for (const pool of mismatchPool) {
    const p = pool[int(0, pool.length - 1)];
    p.price_mismatch = true;
    p.cart_price = p.price + Math.round((p.price * 0.12) / 10) * 10;
  }

  return {
    generated_by: "apps/store/scripts/seed-catalog.ts",
    seed,
    currency: "INR",
    categories: CATEGORIES.map((c) => ({ ...c })),
    products,
  };
}
