import type { Metadata } from "next";
import Link from "next/link";
import HistoryFeed from "./history-feed";

export const metadata: Metadata = {
  title: "Track Record — KTRADES",
  description:
    "Every KTRADES signal and trade, tracked to its outcome and scored after fees and funding.",
};

export default function HistoryPage() {
  return (
    <main className="flex-1">
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <Link href="/" className="text-sm text-muted hover:text-accent">
          ← Live trades
        </Link>
        <h1 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">Track record</h1>
        <p className="mt-2 max-w-2xl text-muted">
          Every result, wins and losses alike. &ldquo;Net&rdquo; is the price move plus the funding
          actually paid or received while open, minus a 0.10% round-trip fee.
        </p>
        <HistoryFeed />
      </div>
      <footer className="border-t border-white/5 py-10 text-center text-sm text-muted">
        KTRADES Signals — not financial advice. Past results don&apos;t predict future ones.
      </footer>
    </main>
  );
}
