const TELEGRAM_URL =
  process.env.NEXT_PUBLIC_TELEGRAM_URL ?? "https://t.me/REPLACE_ME";

const FEATURES = [
  {
    title: "Funding-rate scanner",
    body: "Continuously scans Binance Futures for coins with outsized 1h funding rates, volume, and open interest.",
  },
  {
    title: "Chart-confirmed entries",
    body: "Top signals are filtered through RSI, EMA crossovers, MACD, Bollinger Bands, and ATR before they're posted.",
  },
  {
    title: "Entry, TP, SL, hold time",
    body: "Every confirmed signal comes with a suggested entry, take-profit, stop-loss, and hold-time window.",
  },
  {
    title: "Liquidation cascade alerts",
    body: "Flags clusters of liquidations in real time so you can see volatility building before it shows on the chart.",
  },
];

const STEPS = [
  {
    step: "01",
    title: "Join the channel",
    body: "Tap the button below and join the Telegram channel — it's free.",
  },
  {
    step: "02",
    title: "Get signals as they fire",
    body: "The scanner runs around the clock and posts confirmed setups the moment they qualify.",
  },
  {
    step: "03",
    title: "Trade your own risk",
    body: "Use the entry, TP, and SL as a starting point for your own analysis and risk management.",
  },
];

export default function Home() {
  return (
    <main className="flex-1">
      <div className="mx-auto max-w-5xl px-6">
        <section className="flex min-h-[85vh] flex-col items-center justify-center gap-8 text-center">
          <span className="rounded-full border border-accent-dim/40 bg-accent/10 px-4 py-1 text-sm font-medium text-accent">
            Live Binance Futures signals
          </span>

          <h1 className="text-4xl font-bold tracking-tight text-balance sm:text-6xl">
            Signals that find the move
            <br />
            <span className="text-accent">before it's obvious.</span>
          </h1>

          <p className="max-w-2xl text-lg text-muted text-balance">
            KTRADES scans Binance Futures for high-funding, high-volatility
            setups, confirms them against real chart structure, and drops
            them straight into our Telegram channel.
          </p>

          <a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg bg-accent px-8 py-4 text-lg font-semibold text-background shadow-[0_0_40px_-8px_var(--accent)] transition hover:brightness-110"
          >
            Join the Telegram channel →
          </a>

          <p className="text-sm text-muted">
            Free to join. No spam, just signals.
          </p>
        </section>

        <section className="grid gap-6 border-t border-white/5 py-24 sm:grid-cols-2">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="rounded-xl border border-white/5 bg-surface p-6"
            >
              <h3 className="mb-2 text-lg font-semibold text-accent">
                {f.title}
              </h3>
              <p className="text-muted">{f.body}</p>
            </div>
          ))}
        </section>

        <section className="border-t border-white/5 py-24">
          <h2 className="mb-12 text-center text-3xl font-bold">
            How it works
          </h2>
          <div className="grid gap-8 sm:grid-cols-3">
            {STEPS.map((s) => (
              <div key={s.step} className="text-center">
                <div className="mb-3 font-mono text-sm text-accent-dim">
                  {s.step}
                </div>
                <h3 className="mb-2 text-lg font-semibold">{s.title}</h3>
                <p className="text-muted">{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="border-t border-white/5 py-24 text-center">
          <h2 className="mb-4 text-3xl font-bold">Ready to catch the next move?</h2>
          <a
            href={TELEGRAM_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-6 inline-block rounded-lg bg-accent px-8 py-4 text-lg font-semibold text-background transition hover:brightness-110"
          >
            Join the Telegram channel →
          </a>
        </section>
      </div>

      <footer className="border-t border-white/5 py-10 text-center text-sm text-muted">
        KTRADES Signals — not financial advice. Trade at your own risk.
      </footer>
    </main>
  );
}
