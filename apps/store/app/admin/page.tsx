import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { AdminLogin, AdminPanel } from "../../components/AdminPanel";
import { adminEnabled, isAdminRequest } from "../../lib/admin";
import { readToggles } from "../../lib/friction";

export const metadata = { title: "Admin | Desi Threads (TEST STORE)", robots: { index: false } };

export default async function AdminPage() {
  if (!adminEnabled()) notFound();
  const h = await headers();
  if (!isAdminRequest(h)) return <AdminLogin />;
  return <AdminPanel initial={readToggles()} />;
}
