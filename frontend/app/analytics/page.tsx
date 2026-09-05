"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  BarChart,
  Bar,
} from "recharts";
import AppShell from "@/components/AppShell";
import { api } from "@/lib/api";

type Analytics = {
  totals: { emails: number; decisions: number; safety_hits: number; overrides: number; pending: number };
  by_level: { level: string; n: number }[];
  by_status: { status: string; n: number }[];
  feedback: { type: string; n: number }[];
  accuracy: number | null;
  override_rate: number | null;
  ask_rate_by_day: { day: string; n: number; ask_rate: number | null }[];
};

const LEVEL_LABEL: Record<string, string> = {
  proceed_silently: "Silent",
  proceed_and_notify: "Told you",
  ask_first: "Waiting",
  escalate: "Escalated",
};

export default function AnalyticsPage() {
  const [data, setData] = useState<Analytics | null>(null);

  useEffect(() => {
    api<Analytics>("/analytics").then(setData);
  }, []);

  const line = (data?.ask_rate_by_day || []).map((d) => ({
    day: d.day.slice(5),
    ask: d.ask_rate == null ? null : Math.round(d.ask_rate * 100),
    n: d.n,
  }));

  const bars = (data?.by_level || []).map((d) => ({
    name: LEVEL_LABEL[d.level] || d.level,
    n: d.n,
  }));

  return (
    <AppShell>
      <div className="h-screen overflow-y-auto">
        <div className="mx-auto max-w-3xl px-8 py-8">
          <h1 className="font-serif text-2xl">Calibration</h1>
          <p className="mt-1 text-sm text-ink-500">Ask rate should fall on familiar mail. Safety hits should not.</p>

          <div className="mt-6 grid grid-cols-4 gap-3">
            {[
              ["Mail", data?.totals.emails],
              ["Decisions", data?.totals.decisions],
              ["Safety holds", data?.totals.safety_hits],
              ["Accuracy", data?.accuracy == null ? "n/a" : `${Math.round(data.accuracy * 100)}%`],
            ].map(([k, v]) => (
              <div key={String(k)} className="rounded-lg border border-ink-200 bg-white p-3">
                <p className="text-xs text-ink-400">{k}</p>
                <p className="mt-1 font-serif text-2xl">{v ?? "-"}</p>
              </div>
            ))}
          </div>

          <section className="mt-8 rounded-lg border border-ink-200 bg-white p-4">
            <h2 className="text-sm font-medium">Ask rate (14 days)</h2>
            <p className="text-xs text-ink-400">Share of decisions that were ask-first or escalate.</p>
            <div className="mt-4 h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={line}>
                  <CartesianGrid stroke="#ebe6de" vertical={false} />
                  <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#8f8576" }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "#8f8576" }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="ask" stroke="#3c3832" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="mt-6 rounded-lg border border-ink-200 bg-white p-4">
            <h2 className="text-sm font-medium">Decisions by level</h2>
            <div className="mt-4 h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={bars}>
                  <CartesianGrid stroke="#ebe6de" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#8f8576" }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#8f8576" }} />
                  <Tooltip />
                  <Bar dataKey="n" fill="#524c44" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="mt-6 grid grid-cols-2 gap-4">
            <div className="rounded-lg border border-ink-200 bg-white p-4 text-sm">
              <h2 className="font-medium">Feedback</h2>
              <ul className="mt-2 space-y-1 text-ink-600">
                {(data?.feedback || []).map((f) => (
                  <li key={f.type} className="flex justify-between">
                    <span>{f.type.replace("_", " ")}</span>
                    <span>{f.n}</span>
                  </li>
                ))}
                {(data?.feedback || []).length === 0 ? <li className="text-ink-400">None yet.</li> : null}
              </ul>
            </div>
            <div className="rounded-lg border border-ink-200 bg-white p-4 text-sm">
              <h2 className="font-medium">Status</h2>
              <ul className="mt-2 space-y-1 text-ink-600">
                {(data?.by_status || []).map((f) => (
                  <li key={f.status} className="flex justify-between">
                    <span>{f.status}</span>
                    <span>{f.n}</span>
                  </li>
                ))}
              </ul>
              {data?.override_rate != null ? (
                <p className="mt-3 text-xs text-ink-400">Override rate {Math.round(data.override_rate * 100)}%</p>
              ) : null}
            </div>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
