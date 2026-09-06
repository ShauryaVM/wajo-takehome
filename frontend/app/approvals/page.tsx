"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import DecisionBadge from "@/components/DecisionBadge";
import FeedbackButtons from "@/components/FeedbackButtons";
import { api } from "@/lib/api";
import type { ApprovalItem } from "@/lib/types";
import { plainText } from "@/lib/plain";

function fromName(sender: string) {
  const angle = sender.indexOf("<");
  return (angle >= 0 ? sender.slice(0, angle) : sender).replace(/"/g, "").trim() || sender;
}

export default function ApprovalsPage() {
  const [items, setItems] = useState<ApprovalItem[] | null>(null);

  function load() {
    api<ApprovalItem[]>("/approvals").then(setItems).catch(() => setItems([]));
  }

  useEffect(() => {
    load();
  }, []);

  async function act(id: number, path: "approve" | "dismiss") {
    await api(`/decisions/${id}/${path}`, { method: "POST" });
    load();
  }

  return (
    <AppShell>
      <div className="h-screen overflow-y-auto">
        <div className="mx-auto max-w-2xl px-8 py-8">
          <h1 className="font-serif text-2xl">Waiting on you</h1>
          <p className="mt-1 text-sm text-ink-500">Asks and escalations. Nothing here goes out until you say so.</p>
          <div className="mt-8 space-y-5">
            {items === null ? <p className="text-sm text-ink-400">Loading...</p> : null}
            {items?.length === 0 ? (
              <p className="text-sm text-ink-400">Caught up. The agent has nothing queued.</p>
            ) : null}
            {items?.map((item) => {
              const d = item.decision;
              const draft = d.proposed_action?.draft;
              const types = (item.feedback || []).map((f) => f.feedback_type);
              return (
                <article key={d.id} className="rounded-lg border border-ink-200 bg-white p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium">{fromName(item.email.sender)}</p>
                      <p className="text-sm text-ink-800">{item.email.subject}</p>
                    </div>
                    <DecisionBadge level={d.autonomy_level} status={d.status} />
                  </div>
                  <pre className="mt-4 max-h-40 overflow-y-auto whitespace-pre-wrap font-sans text-sm leading-6 text-ink-700">
                    {plainText(item.email.body_text)}
                  </pre>
                  <p className="mt-3 text-sm text-ink-600">{d.reasoning}</p>
                  {typeof draft === "string" && draft ? (
                    <div className="mt-3 rounded-md bg-ink-50 p-3 text-sm">
                      <p className="text-xs text-ink-400">Draft</p>
                      <p className="mt-1 whitespace-pre-wrap">{draft}</p>
                    </div>
                  ) : null}
                  {d.safety_hit ? (
                    <p className="mt-2 text-xs text-rust-500">Held by safety floor ({d.safety_hit}).</p>
                  ) : null}
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    {d.action_type !== "none" ? (
                      <button
                        onClick={() => act(d.id, "approve")}
                        className="rounded-md bg-ink-900 px-3 py-1.5 text-xs text-white hover:bg-ink-800"
                      >
                        Approve {d.action_type.replace("_", " ")}
                      </button>
                    ) : null}
                    <button
                      onClick={() => act(d.id, "dismiss")}
                      className="rounded-md border border-ink-200 px-3 py-1.5 text-xs text-ink-600 hover:bg-ink-50"
                    >
                      Dismiss
                    </button>
                    <FeedbackButtons decisionId={d.id} existing={types} onDone={load} />
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
