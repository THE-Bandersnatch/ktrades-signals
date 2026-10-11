import type { Metadata } from "next";
import Link from "next/link";
import LiveFeed from "./live-feed";

export const metadata: Metadata = {
  title: "Live Signals — KTRADES",
  description:
    "Every KTRADES signal as it fires, with its outcome and net result after fees and funding.",
};

export default function LivePage() {
  return (
    <main className="flex-1">
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <Link href="/" className="text-sm text-muted hover:text-accent">
              ← KTRADES
            </Link>
            <h1 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">
              Live signals
            </h1>
            <p className="mt-2 max-w-2xl text-muted">
              Every signal the scanner posts, tracked to its outcome. Results
              are net of a 0.10% round-trip fee and include the funding
              actually paid or received while the trade was open.
            </p>
          </div>
        </header>
        <LiveFeed />
      </div>
      <footer className="border-t border-white/5 py-10 text-center text-sm text-muted">
        KTRADES Signals — not financial advice. Past results don&apos;t
        predict future ones. Trade at your own risk.
      </footer>
    </main>
  );
}
