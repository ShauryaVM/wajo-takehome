import { cn } from "@/lib/cn";
import type { AutonomyLevel } from "@/lib/types";

const COPY: Record<AutonomyLevel, { label: string; className: string }> = {
  proceed_silently: { label: "Silent", className: "bg-ink-100 text-ink-600" },
  proceed_and_notify: { label: "Told you", className: "bg-emerald-50 text-moss-600" },
  ask_first: { label: "Waiting", className: "bg-amber-50 text-amber-800" },
  escalate: { label: "Escalated", className: "bg-red-50 text-rust-500" },
};

export default function DecisionBadge({
  level,
  status,
}: {
  level?: string | null;
  status?: string | null;
}) {
  if (!level) return <span className="text-xs text-ink-300">unread</span>;
  const meta = COPY[level as AutonomyLevel] || { label: level, className: "bg-ink-100 text-ink-600" };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", meta.className)}>
      {meta.label}
      {status && status !== "pending" && status !== "escalated" ? (
        <span className="opacity-70">· {status}</span>
      ) : null}
    </span>
  );
}
