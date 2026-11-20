import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { THEME_INIT_SCRIPT } from "@/lib/theme-script";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://agentlens.ptlabs.in";
const TITLE = "AgentLens - Agent Readiness";
const DESCRIPTION = "See how AI shopping agents experience your store, what blocks them, and what to fix first.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: TITLE,
  description: DESCRIPTION,
  openGraph: { title: TITLE, description: DESCRIPTION, url: "/", siteName: "AgentLens", type: "website", images: [{ url: "/og.png", width: 1200, height: 630, alt: "AgentLens dashboard" }] },
  twitter: { card: "summary_large_image", title: TITLE, description: DESCRIPTION, images: ["/og.png"] },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-IN" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* Fonts are mandated by docs/theme.md; the root layout covers every page. */}
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Sora:wght@400;500;600;700&display=swap"
        />
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
