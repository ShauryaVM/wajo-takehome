"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";

export default function Page() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    api<{ email: string }>("/auth/me")
      .then((me) => setEmail(me.email))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        }
      });
  }, [router]);

  if (!email) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-ink-50 text-sm text-ink-400">
        Checking session...
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-ink-50 text-ink-900">
      <div className="max-w-md px-6">
        <p className="font-serif text-3xl">Steward</p>
        <p className="mt-3 text-sm text-ink-500">Signed in as {email}. Inbox comes next.</p>
      </div>
    </main>
  );
}
