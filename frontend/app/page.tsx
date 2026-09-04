export default function Page() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-ink-50 text-ink-900">
      <div className="max-w-md px-6">
        <p className="font-serif text-3xl">Steward</p>
        <p className="mt-3 text-sm text-ink-500">
          Local email agent. API health is at{" "}
          <code className="text-ink-800">localhost:8000/health</code>.
        </p>
      </div>
    </main>
  );
}
