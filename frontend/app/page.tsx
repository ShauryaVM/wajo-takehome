"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import DecisionBadge from "@/components/DecisionBadge";
import FeedbackButtons from "@/components/FeedbackButtons";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { EmailDetail, EmailListItem } from "@/lib/types";

function fromName(sender: string) {
  const angle = sender.indexOf("<");
  const name = (angle >= 0 ? sender.slice(0, angle) : sender).replace(/"/g, "").trim();
  return name || sender;
}

function relative(iso: string) {
  const t = new Date(iso).getTime();
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins < 60) return `${Math.max(mins, 0)}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.round(hrs / 24);
  return `${days}d`;
}

export default function InboxPage() {
  const [emails, setEmails] = useState<EmailListItem[] | null>(null);
  const [selected, setSelected] = useState<EmailDetail | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    api<EmailListItem[]>(`/emails${q ? `?q=${encodeURIComponent(q)}` : ""}`)
      .then((rows) => {
        setEmails(rows);
        setErr("");
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "failed to load"));
  }, [q]);

  async function open(id: number) {
    const detail = await api<EmailDetail>(`/emails/${id}`);
    setSelected(detail);
  }

  return (
    <AppShell>
      <div className="flex h-screen">
        <div className="flex w-[380px] shrink-0 flex-col border-r border-ink-200 bg-white">
          <div className="border-b border-ink-100 px-4 py-3">
            <div className="flex items-baseline justify-between">
              <h1 className="font-serif text-xl">Inbox</h1>
              <span className="text-xs text-ink-400">{emails?.length ?? 0}</span>
            </div>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search"
              className="mt-2 w-full rounded-md border border-ink-200 bg-ink-50 px-2 py-1.5 text-sm outline-none focus:border-ink-400"
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {err ? <p className="px-4 py-3 text-sm text-rust-500">{err}</p> : null}
            {emails === null ? <p className="px-4 py-3 text-sm text-ink-400">Loading mail...</p> : null}
            {emails?.length === 0 ? (
              <p className="px-4 py-6 text-sm text-ink-400">Nothing here yet. Try Sync mail.</p>
            ) : null}
            {emails?.map((e) => {
              const active = selected?.id === e.id;
              return (
                <button
                  key={e.id}
                  onClick={() => open(e.id)}
                  className={cn(
                    "block w-full border-b border-ink-100 px-4 py-3 text-left hover:bg-ink-50",
                    active && "bg-ink-100",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="truncate text-sm font-medium">{fromName(e.sender)}</p>
                    <span className="shrink-0 text-[11px] text-ink-400">{relative(e.received_at)}</span>
                  </div>
                  <p className="mt-0.5 truncate text-sm text-ink-800">{e.subject || "(no subject)"}</p>
                  <p className="mt-0.5 truncate text-xs text-ink-400">{e.preview}</p>
                  <div className="mt-1.5">
                    <DecisionBadge level={e.decision?.autonomy_level} status={e.decision?.status} />
                  </div>
                </button>
              );
            })}
          </div>
        </div>
        <div className="min-w-0 flex-1 overflow-y-auto bg-white">
          {!selected ? (
            <div className="flex h-full items-center justify-center text-sm text-ink-400">
              Pick a message.
            </div>
          ) : (
            <article className="mx-auto max-w-2xl px-8 py-8">
              <div className="flex items-start justify-between gap-4">
                <h2 className="font-serif text-2xl leading-tight">{selected.subject || "(no subject)"}</h2>
                <DecisionBadge level={selected.decision?.autonomy_level} status={selected.decision?.status} />
              </div>
              <p className="mt-3 text-sm text-ink-600">
                {selected.sender}
                <span className="text-ink-400"> → {(selected.to_addresses || []).join(", ") || "you"}</span>
              </p>
              <p className="mt-1 text-xs text-ink-400">{new Date(selected.received_at).toLocaleString()}</p>
              <pre className="mt-8 whitespace-pre-wrap font-sans text-sm leading-6 text-ink-800">
                {selected.body_text}
              </pre>
                  {selected.decision ? (
                <section className="mt-10 rounded-lg border border-ink-200 bg-ink-50 p-4">
                  <p className="text-xs uppercase tracking-wide text-ink-400">Agent</p>
                  <p className="mt-2 text-sm text-ink-800">{selected.decision.reasoning}</p>
                  <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-ink-500">
                    <div>
                      Classifier: {selected.decision.classifier_level} ({Math.round(selected.decision.confidence * 100)}%)
                    </div>
                    <div>Action: {selected.decision.action_type}</div>
                    {selected.decision.safety_hit ? (
                      <div className="col-span-2 text-rust-500">
                        Safety floor: {selected.decision.safety_hit}
                      </div>
                    ) : null}
                  </dl>
                  {typeof selected.decision.proposed_action?.draft === "string" &&
                  selected.decision.proposed_action.draft ? (
                    <div className="mt-3 rounded-md border border-ink-200 bg-white p-3 text-sm">
                      <p className="text-xs text-ink-400">Draft reply</p>
                      <p className="mt-1 whitespace-pre-wrap">{String(selected.decision.proposed_action.draft)}</p>
                    </div>
                  ) : null}
                  <div className="mt-3">
                    <FeedbackButtons
                      decisionId={selected.decision.id}
                      existing={(selected.feedback || []).map((f) => f.feedback_type)}
                      onDone={() => open(selected.id)}
                    />
                  </div>
                </section>
              ) : null}
            </article>
          )}
        </div>
      </div>
    </AppShell>
  );
}
