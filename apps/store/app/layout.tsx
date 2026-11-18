import "./globals.css";

export const metadata = { title: "Desi Threads (TEST STORE)" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN">
      <body>{children}</body>
    </html>
  );
}
