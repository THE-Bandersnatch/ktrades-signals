import Link from "next/link";
import LiveBoard, { LivePulse } from "./components/live-board";

const TELEGRAM_URL =
  process.env.NEXT_PUBLIC_TELEGRAM_URL ?? "https://t.me/REPLACE_ME";

const STEPS = [
  {
    icon: "📡",
    title: "Scan",
    body: "Every 30 minutes the scanner reads funding, volume and open interest across all Binance USDT futures.",
  },
  {
    icon: "🧭",
    title: "Filter",
    body: "Only coins where the crowd has been paying extreme funding for hours, not a one-off spike, make the cut.",
  },
  {
    icon: "📈",
    title: "Confirm",
    body: "RSI, EMA, MACD and Bollinger structure must agree before a setup becomes a trade with entry, TP and SL.",
  },
  {
    icon: "🧾",
    title: "Track",
    body: "Every trade is followed to the end and scored after fees and funding. Losses get posted too.",
  },
];

export default function Home() {
  return (
    <main className="flex-1">
      <section className="relative overflow-hidden">
        <div className="hero-grid pointer-events-none absolute inset-0" />
        <div className="relative mx-auto flex max-w-5xl flex-col items-center gap-6 px-4 pb-14 pt-16 text-center sm:px-6 sm:pt-24">
          <span className="rounded-full border border-accent-dim/40 bg-accent/10 px-4 py-1 text-sm font-medium text-accent">
            Live Binance Futures signals
          </span>
          <h1 className="text-4xl font-bold tracking-tight text-balance sm:text-6xl">
            Follow the crowd&apos;s mistakes,
            <br />
            <span className="text-accent">live.</span>
          </h1>
          <p className="max-w-2xl text-lg text-muted text-balance">
            KTRADES hunts for coins where traders are paying through the nose to stay
            positioned, confirms the setup on the chart, and posts it right here and
            in Telegram, with every result tracked in public.
          </p>
          <LivePulse />
          <div className="flex flex-wrap justify-center gap-3">
            <a
              href={TELEGRAM_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-full bg-accent px-6 py-3 font-semibold text-background shadow-[0_0_40px_-8px_var(--accent)] transition hover:brightness-110"
            >
              Join the Telegram channel →
            </a>
            <Link
              href="/history"
              className="rounded-full border border-white/10 px-6 py-3 font-semibold transition hover:border-accent/40 hover:text-accent"
            >
              Track record
            </Link>
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-5xl px-4 pb-20 sm:px-6">
        <LiveBoard telegramUrl={TELEGRAM_URL} />

        <section className="mt-20 border-t border-white/5 pt-16">
          <h2 className="mb-10 text-center text-2xl font-bold sm:text-3xl">How a trade is born</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <div key={s.title} className="rounded-3xl border border-white/5 bg-surface p-5">
                <div className="flex items-center gap-3">
                  <span className="grid h-10 w-10 place-items-center rounded-2xl bg-accent/10 text-xl">{s.icon}</span>
                  <span className="font-mono text-xs text-accent-dim">0{i + 1}</span>
                </div>
                <h3 className="mt-4 font-semibold">{s.title}</h3>
                <p className="mt-1 text-sm text-muted">{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-16 overflow-hidden rounded-3xl border border-accent/20 bg-gradient-to-br from-accent/15 via-surface to-surface p-8 text-center sm:p-12">
          <div className="text-4xl">🔔</div>
          <h2 className="mt-3 text-2xl font-bold sm:text-3xl">Never miss the next trade</h2>
          <p className="mx-auto mt-2 max-w-lg text-muted">
            Trades fire at any hour. The Telegram channel pings you the second one does, and
            again when it closes.
          </p>
          <a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-6 inline-block rounded-full bg-accent px-8 py-3.5 font-semibold text-background transition hover:brightness-110"
          >
            Join free on Telegram →
          </a>
        </section>
      </div>

      <footer className="border-t border-white/5 py-10 text-center text-sm text-muted">
        <div className="flex flex-wrap justify-center gap-4">
          <Link href="/history" className="hover:text-accent">Track record</Link>
          <a href={TELEGRAM_URL} target="_blank" rel="noopener noreferrer" className="hover:text-accent">
            Telegram
          </a>
        </div>
        <p className="mt-4 px-4">
          KTRADES Signals — not financial advice. Futures are high risk and past results don&apos;t
          predict future ones.
        </p>
      </footer>
    </main>
  );
}
