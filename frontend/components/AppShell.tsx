"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/", label: "Inbox" },
  { href: "/feed", label: "Feed" },
  { href: "/approvals", label: "Approvals" },
  { href: "/analytics", label: "Analytics" },
  { href: "/settings", label: "Settings" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    api<{ email: string }>("/auth/me")
      .then((me) => setEmail(me.email))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
      });
    api<{ totals: { pending: number } }>("/analytics")
      .then((a) => setPending(a.totals.pending))
      .catch(() => {});
  }, [router, pathname]);

  async function syncNow() {
    setSyncing(true);
    try {
      await api("/sync", { method: "POST" });
      router.refresh();
      window.location.reload();
    } finally {
      setSyncing(false);
    }
  }

  async function logout() {
    await api("/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  if (!email) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink-50 text-sm text-ink-400">
        Loading...
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-ink-50 text-ink-900">
      <aside className="flex w-56 shrink-0 flex-col border-r border-ink-200 bg-[#f3efe8] px-4 py-5">
        <Link href="/" className="font-serif text-2xl tracking-tight">
          Steward
        </Link>
        <p className="mt-1 text-xs text-ink-400">{email}</p>
        <nav className="mt-8 space-y-1">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center justify-between rounded-md px-2 py-1.5 text-sm",
                  active ? "bg-ink-900 text-ink-50" : "text-ink-600 hover:bg-ink-100",
                )}
              >
                <span>{item.label}</span>
                {item.href === "/approvals" && pending > 0 ? (
                  <span className={cn("text-xs", active ? "text-ink-200" : "text-ink-400")}>{pending}</span>
                ) : null}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto space-y-2 pt-6">
          <button
            onClick={syncNow}
            disabled={syncing}
            className="w-full rounded-md border border-ink-200 bg-white px-2 py-1.5 text-left text-xs text-ink-600 hover:bg-ink-100 disabled:opacity-50"
          >
            {syncing ? "Syncing..." : "Sync mail"}
          </button>
          <button onClick={logout} className="w-full px-2 text-left text-xs text-ink-400 hover:text-ink-700">
            Sign out
          </button>
        </div>
      </aside>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
