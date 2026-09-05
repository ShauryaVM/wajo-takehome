"use client";

import { FormEvent, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { api } from "@/lib/api";

type Account = {
  id: number;
  provider: string;
  email_address: string;
  display_name: string;
  is_active: boolean;
  last_sync_at: string | null;
  imap_host: string | null;
};

type Rule = {
  id: number;
  rule_type: string;
  action_type: string;
  min_autonomy_level: string;
  is_system: boolean;
  label: string;
};

type Settings = {
  llm: {
    provider: string;
    openai_configured: boolean;
    anthropic_configured: boolean;
    ready: boolean;
    openai_model: string;
    anthropic_model: string;
  };
  safety_rules: Rule[];
  user: { email: string };
  google_oauth_configured: boolean;
  microsoft_oauth_configured: boolean;
  gmail_redirect_uri: string;
};

const GMAIL_DEFAULTS = {
  email_address: "",
  password: "",
  imap_host: "imap.gmail.com",
  imap_port: 993,
  smtp_host: "smtp.gmail.com",
  smtp_port: 587,
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  const [imap, setImap] = useState(GMAIL_DEFAULTS);
  const [extra, setExtra] = useState({ rule_type: "vip_sender", min_autonomy_level: "ask_first", label: "VIP senders" });

  function load() {
    api<Settings>("/settings").then(setSettings);
    api<Account[]>("/accounts").then(setAccounts);
  }

  useEffect(() => {
    load();
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("connected");
    const error = params.get("error");
    if (connected) {
      window.history.replaceState({}, "", "/settings");
      setMsg(`Connected ${connected}. Syncing...`);
      api<{ new_messages: number }>("/sync", { method: "POST" })
        .then((s) => {
          setMsg(`Connected ${connected}. ${s.new_messages} new messages pulled.`);
          load();
        })
        .catch(() => {
          setMsg(`Connected ${connected}. Hit Sync mail, or wait about 45s for the worker.`);
        });
    } else if (error) {
      window.history.replaceState({}, "", "/settings");
      setMsg(`OAuth failed (${error}). App Password IMAP below does not need Google verification.`);
    }
  }, []);

  async function startOauth(kind: "gmail" | "outlook") {
    try {
      const res = await api<{ url: string }>(`/accounts/${kind}/start`);
      window.location.href = res.url;
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "oauth not configured");
    }
  }

  async function testImap() {
    setBusy("test");
    setMsg("");
    try {
      await api("/accounts/imap/test", { method: "POST", body: JSON.stringify(imap) });
      setMsg("IMAP and SMTP login succeeded. Save to start polling.");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "connection failed");
    } finally {
      setBusy("");
    }
  }

  async function connectImap(e: FormEvent) {
    e.preventDefault();
    setBusy("save");
    setMsg("");
    try {
      await api("/accounts/imap", { method: "POST", body: JSON.stringify(imap) });
      setImap({ ...imap, password: "" });
      setMsg("Saved. Syncing latest mail...");
      load();
      try {
        const s = await api<{ new_messages: number }>("/sync", { method: "POST" });
        setMsg(`Connected. ${s.new_messages} new messages classified. Worker keeps polling.`);
        load();
      } catch {
        setMsg("Saved. Worker will poll within a minute, or hit Sync mail.");
      }
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "could not save imap");
    } finally {
      setBusy("");
    }
  }

  async function disconnect(id: number) {
    setBusy(`drop-${id}`);
    try {
      await api(`/accounts/${id}`, { method: "DELETE" });
      setMsg("Disconnected. Demo inbox is back if that was the last live mailbox.");
      load();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "could not disconnect");
    } finally {
      setBusy("");
    }
  }

  async function addRule(e: FormEvent) {
    e.preventDefault();
    await api("/settings/safety", {
      method: "POST",
      body: JSON.stringify({ ...extra, action_type: "*" }),
    });
    load();
  }

  async function dropRule(id: number) {
    await api(`/settings/safety/${id}`, { method: "DELETE" });
    load();
  }

  return (
    <AppShell>
      <div className="h-screen overflow-y-auto">
        <div className="mx-auto max-w-2xl px-8 py-8">
          <h1 className="font-serif text-2xl">Settings</h1>
          <p className="mt-1 text-sm text-ink-500">Local instance. App passwords are encrypted in Postgres, not stored in .env.</p>
          {msg ? <p className="mt-3 text-sm text-moss-600">{msg}</p> : null}

          <section className="mt-8">
            <h2 className="text-sm font-medium">Mailboxes</h2>
            <ul className="mt-3 divide-y divide-ink-100 rounded-lg border border-ink-200 bg-white">
              {accounts.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                  <div>
                    <p className="font-medium">{a.email_address}</p>
                    <p className="text-xs text-ink-400">
                      {a.provider}
                      {a.imap_host ? ` · ${a.imap_host}` : ""}
                      {a.last_sync_at ? ` · synced ${new Date(a.last_sync_at).toLocaleString()}` : " · never synced"}
                      {a.is_active ? "" : " · off"}
                    </p>
                  </div>
                  {a.provider !== "fixture" && a.is_active ? (
                    <button
                      onClick={() => disconnect(a.id)}
                      disabled={busy === `drop-${a.id}`}
                      className="text-xs text-ink-400 hover:text-rust-500 disabled:opacity-50"
                    >
                      Disconnect
                    </button>
                  ) : (
                    <span className="text-xs text-ink-400">{a.is_active ? "active" : "off"}</span>
                  )}
                </li>
              ))}
              {accounts.length === 0 ? (
                <li className="px-4 py-3 text-sm text-ink-400">No accounts yet. Seed should create the demo inbox.</li>
              ) : null}
            </ul>
          </section>

          <section className="mt-10">
            <h2 className="text-sm font-medium">Gmail (App Password)</h2>
            <p className="mt-1 text-xs text-ink-400">
              This is the path that works without Google app verification. Turn on 2-Step Verification, create an App
              Password, enable IMAP in Gmail, then paste it here. Do not use your normal Gmail password.
            </p>
            <form onSubmit={connectImap} className="mt-3 grid grid-cols-2 gap-3 rounded-lg border border-ink-200 bg-white p-4 text-sm">
              <label className="col-span-2">
                Gmail address
                <input
                  type="email"
                  required
                  autoComplete="username"
                  className="mt-1 w-full rounded-md border border-ink-200 px-2 py-1.5"
                  value={imap.email_address}
                  onChange={(e) => setImap({ ...imap, email_address: e.target.value })}
                />
              </label>
              <label className="col-span-2">
                App password
                <input
                  type="password"
                  required
                  autoComplete="current-password"
                  className="mt-1 w-full rounded-md border border-ink-200 px-2 py-1.5"
                  value={imap.password}
                  onChange={(e) => setImap({ ...imap, password: e.target.value })}
                />
              </label>
              <label>
                IMAP host
                <input
                  className="mt-1 w-full rounded-md border border-ink-200 px-2 py-1.5"
                  value={imap.imap_host}
                  onChange={(e) => setImap({ ...imap, imap_host: e.target.value })}
                />
              </label>
              <label>
                IMAP port
                <input
                  type="number"
                  className="mt-1 w-full rounded-md border border-ink-200 px-2 py-1.5"
                  value={imap.imap_port}
                  onChange={(e) => setImap({ ...imap, imap_port: Number(e.target.value) })}
                />
              </label>
              <label>
                SMTP host
                <input
                  className="mt-1 w-full rounded-md border border-ink-200 px-2 py-1.5"
                  value={imap.smtp_host}
                  onChange={(e) => setImap({ ...imap, smtp_host: e.target.value })}
                />
              </label>
              <label>
                SMTP port
                <input
                  type="number"
                  className="mt-1 w-full rounded-md border border-ink-200 px-2 py-1.5"
                  value={imap.smtp_port}
                  onChange={(e) => setImap({ ...imap, smtp_port: Number(e.target.value) })}
                />
              </label>
              <div className="col-span-2 flex gap-2">
                <button
                  type="button"
                  onClick={testImap}
                  disabled={busy !== ""}
                  className="flex-1 rounded-md border border-ink-200 py-1.5 text-xs hover:bg-ink-50 disabled:opacity-50"
                >
                  {busy === "test" ? "Testing..." : "Test connection"}
                </button>
                <button
                  type="submit"
                  disabled={busy !== ""}
                  className="flex-1 rounded-md bg-ink-900 py-1.5 text-xs text-white disabled:opacity-50"
                >
                  {busy === "save" ? "Saving..." : "Save and sync"}
                </button>
              </div>
            </form>
          </section>

          <section className="mt-10">
            <h2 className="text-sm font-medium">Gmail API / Outlook (optional)</h2>
            <p className="mt-1 text-xs text-ink-400">
              Unverified Google Cloud OAuth. Add your Google account as a test user, register redirect
              {settings?.gmail_redirect_uri ? ` ${settings.gmail_redirect_uri}` : " http://localhost:8000/accounts/gmail/callback"}
              , then put GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env. Only test users can connect until Google verifies the app.
            </p>
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => startOauth("gmail")}
                disabled={!settings?.google_oauth_configured}
                className="rounded-md border border-ink-200 bg-white px-3 py-1.5 text-xs hover:bg-ink-50 disabled:opacity-50"
              >
                Connect Gmail with Google
              </button>
              <button
                onClick={() => startOauth("outlook")}
                disabled={!settings?.microsoft_oauth_configured}
                className="rounded-md border border-ink-200 bg-white px-3 py-1.5 text-xs hover:bg-ink-50 disabled:opacity-50"
              >
                Connect Outlook
              </button>
            </div>
            {settings && !settings.google_oauth_configured ? (
              <p className="mt-2 text-xs text-ink-400">Gmail OAuth button stays off until client IDs are in .env. App Password above still works.</p>
            ) : null}
          </section>

          <section className="mt-10">
            <h2 className="text-sm font-medium">LLM</h2>
            {settings ? (
              <dl className="mt-3 space-y-1 rounded-lg border border-ink-200 bg-white p-4 text-sm text-ink-600">
                <div>Provider: {settings.llm.provider}</div>
                <div>OpenAI key: {settings.llm.openai_configured ? "set" : "missing"} ({settings.llm.openai_model})</div>
                <div>Anthropic key: {settings.llm.anthropic_configured ? "set" : "missing"} ({settings.llm.anthropic_model})</div>
                <div>
                  {settings.llm.ready
                    ? "Classifier will call the configured model."
                    : "No key set. Classifier uses the local heuristic. Fine for the demo and eval."}
                </div>
              </dl>
            ) : null}
          </section>

          <section className="mt-10">
            <h2 className="text-sm font-medium">Safety floor</h2>
            <p className="mt-1 text-xs text-ink-400">System rules cannot be lowered. You can only add stricter ones. Send/reply still ask first. Delete, forward, money, and injection still escalate.</p>
            <ul className="mt-3 divide-y divide-ink-100 rounded-lg border border-ink-200 bg-white">
              {settings?.safety_rules.map((r) => (
                <li key={r.id} className="flex items-center justify-between px-4 py-3 text-sm">
                  <div>
                    <p>{r.label || r.rule_type}</p>
                    <p className="text-xs text-ink-400">
                      min {r.min_autonomy_level}
                      {r.is_system ? " · system" : ""}
                    </p>
                  </div>
                  {!r.is_system ? (
                    <button onClick={() => dropRule(r.id)} className="text-xs text-ink-400 hover:text-rust-500">
                      Remove
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
            <form onSubmit={addRule} className="mt-3 flex flex-wrap items-end gap-2 text-sm">
              <label>
                Name
                <input
                  className="mt-1 block rounded-md border border-ink-200 px-2 py-1.5"
                  value={extra.label}
                  onChange={(e) => setExtra({ ...extra, label: e.target.value, rule_type: e.target.value.toLowerCase().replace(/\s+/g, "_") })}
                />
              </label>
              <label>
                Floor
                <select
                  className="mt-1 block rounded-md border border-ink-200 px-2 py-1.5"
                  value={extra.min_autonomy_level}
                  onChange={(e) => setExtra({ ...extra, min_autonomy_level: e.target.value })}
                >
                  <option value="ask_first">ask first</option>
                  <option value="escalate">escalate</option>
                </select>
              </label>
              <button type="submit" className="rounded-md border border-ink-200 px-3 py-1.5 text-xs">
                Add rule
              </button>
            </form>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
