import SLink from "./SLink";

export default function Footer() {
  return (
    <footer className="mt-16 border-t border-stone-200 bg-stone-100 text-sm text-stone-600">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-6">
        <p>Desi Threads is a demo store for AgentLens. No real orders, no real payments.</p>
        <ul className="flex gap-5">
          <li>
            <SLink href="/policies/returns" className="hover:text-rust-700">
              Returns policy
            </SLink>
          </li>
          <li>
            <SLink href="/size-guide/mens-shirts" className="hover:text-rust-700">
              Size guide
            </SLink>
          </li>
        </ul>
      </div>
    </footer>
  );
}
