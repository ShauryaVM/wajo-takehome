"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import DecisionBadge from "@/components/DecisionBadge";
import FeedbackButtons from "@/components/FeedbackButtons";
import { api } from "@/lib/api";
import type { FeedItem } from "@/lib/types";

function fromName(sender: string) {
  const angle = sender.indexOf("<");
  return (angle >= 0 ? sender.slice(0, angle) : sender).replace(/"/g, "").trim() || sender;
}

export default function FeedPage() {
  const [items, setItems] = useState<FeedItem[] | null>(null);

  function load() {
    api<FeedItem[]>("/feed").then(setItems).catch(() => setItems([]));
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <AppShell>
      <div className="h-screen overflow-y-auto">
        <div className="mx-auto max-w-2xl px-8 py-8">
          <h1 className="font-serif text-2xl">Agent feed</h1>
          <p className="mt-1 text-sm text-ink-500">What it did and told you about, plus asks and flags. Silent work stays off this list.</p>
          <ol className="mt-8 space-y-4">
            {items === null ? <p className="text-sm text-ink-400">Loading...</p> : null}
            {items?.length === 0 ? <p className="text-sm text-ink-400">No decisions yet.</p> : null}
            {items?.map((item) => {
              const d = item.decision;
              const types = item.feedback.map((f) => f.feedback_type);
              return (
                <li key={d.id} className="rounded-lg border border-ink-200 bg-white p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{fromName(item.email.sender)}</p>
                      <p className="truncate text-sm text-ink-700">{item.email.subject}</p>
                    </div>
                    <DecisionBadge level={d.autonomy_level} status={d.status} />
                  </div>
                  <p className="mt-2 text-sm text-ink-600">{d.reasoning}</p>
                  <p className="mt-1 text-xs text-ink-400">
                    {d.action_type}
                    {d.safety_hit ? ` · floor: ${d.safety_hit}` : ""}
                    {" · "}
                    {new Date(d.created_at).toLocaleString()}
                  </p>
                  <div className="mt-3">
                    <FeedbackButtons decisionId={d.id} existing={types} onDone={load} />
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </AppShell>
  );
}
