import SLink from "./SLink";

const NAV = [
  { href: "/c/mens-sneakers", label: "Men's sneakers" },
  { href: "/c/womens-kurtas", label: "Women's kurtas" },
  { href: "/c/mens-shirts", label: "Men's shirts" },
  { href: "/c/accessories", label: "Accessories" },
];

export default function Header() {
  return (
    <header className="border-b border-stone-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-4">
        <SLink href="/" className="font-serif text-2xl font-bold tracking-tight text-rust-700">
          Desi Threads
        </SLink>
        <form action="/search" method="get" role="search" className="ml-auto flex w-full max-w-md">
          <input
            name="q"
            type="search"
            placeholder="Search kurtas, sneakers, shirts"
            aria-label="Search products"
            className="w-full rounded-l border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-rust-600"
          />
          <button type="submit" className="rounded-r bg-rust-700 px-4 text-sm font-medium text-white hover:bg-rust-800">
            Search
          </button>
        </form>
        <SLink href="/cart" className="text-sm font-medium text-stone-700 hover:text-rust-700">
          Cart
        </SLink>
        <SLink href="/login" className="text-sm font-medium text-stone-700 hover:text-rust-700">
          Login
        </SLink>
      </div>
      <nav aria-label="Categories" className="border-t border-stone-100 bg-stone-50">
        <ul className="mx-auto flex max-w-6xl gap-6 px-4 py-2 text-sm text-stone-700">
          {NAV.map((n) => (
            <li key={n.href}>
              <SLink href={n.href} className="hover:text-rust-700">
                {n.label}
              </SLink>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
