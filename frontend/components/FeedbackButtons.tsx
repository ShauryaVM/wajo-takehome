"use client";

import { api } from "@/lib/api";

const OPTIONS = [
  { type: "good", label: "Good call" },
  { type: "too_aggressive", label: "Too aggressive" },
  { type: "too_cautious", label: "Too cautious" },
  { type: "wrong_action", label: "Wrong action" },
] as const;

export default function FeedbackButtons({
  decisionId,
  existing,
  onDone,
}: {
  decisionId: number;
  existing?: string[];
  onDone?: () => void;
}) {
  const already = existing || [];

  async function send(type: string) {
    await api(`/decisions/${decisionId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ feedback_type: type }),
    });
    onDone?.();
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {OPTIONS.map((opt) => {
        const used = already.includes(opt.type);
        return (
          <button
            key={opt.type}
            disabled={used}
            onClick={() => send(opt.type)}
            className="rounded-full border border-ink-200 bg-white px-2.5 py-0.5 text-[11px] text-ink-600 hover:bg-ink-50 disabled:opacity-40"
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
