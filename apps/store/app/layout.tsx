import "./globals.css";
import type { Metadata } from "next";
import Beacon from "../components/Beacon";
import Footer from "../components/Footer";
import Header from "../components/Header";

// Friction toggles change what every page renders, so nothing is prerendered.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Desi Threads (TEST STORE)",
  description: "Indian fashion and footwear. Demo store for AgentLens: no real orders.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">
        <div role="status" className="bg-stone-900 py-1 text-center text-xs font-medium tracking-wide text-amber-300">
          TEST STORE: no real orders
        </div>
        <Header />
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
        <Footer />
        <Beacon />
      </body>
    </html>
  );
}
