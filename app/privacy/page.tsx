import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy — KTRADES",
  description: "How the KTRADES Signals website and Android app handle your data.",
};

const UPDATED = "November 9, 2026";

export default function PrivacyPage() {
  return (
    <main className="flex-1">
      <article className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
        <Link href="/" className="text-sm text-muted hover:text-accent">
          ← Live trades
        </Link>
        <h1 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">Privacy Policy</h1>
        <p className="mt-2 text-sm text-muted">Last updated {UPDATED}</p>

        <div className="mt-8 space-y-8 leading-relaxed text-foreground/90">
          <Section title="Summary">
            KTRADES Signals (the website and the Android app, which shows the same website) does
            not ask you to create an account, does not collect your name, email, location or
            contacts, and does not use advertising or analytics trackers.
          </Section>

          <Section title="Information we do not collect">
            We don&apos;t collect personal information, device identifiers, precise or approximate
            location, payment details, or the contents of your device. The app doesn&apos;t request
            any Android permissions beyond internet access.
          </Section>

          <Section title="Information processed automatically">
            <p>
              Like any website, our hosting provider (Vercel) receives standard request data such
              as your IP address, browser type and the pages requested. It uses this data to
              deliver and secure the service and keeps it for a short period in server logs.
            </p>
            <p className="mt-3">
              To show live funding rates, your browser or app loads public market data directly
              from Binance (fapi.binance.com). Binance receives your IP address for those requests
              under its own privacy policy. We don&apos;t send Binance any information about you.
            </p>
          </Section>

          <Section title="Telegram">
            If you choose to join our Telegram channel or message our Telegram bot, Telegram
            processes that under its own privacy policy. The bot uses your chat ID only to send its
            reply and doesn&apos;t store it in any database; it may appear briefly in server logs.
            You can stop at any time by leaving the channel or blocking the bot.
          </Section>

          <Section title="Cookies and local storage">
            We don&apos;t set tracking or advertising cookies.
          </Section>

          <Section title="Children">
            KTRADES is meant for adults and isn&apos;t directed at anyone under 18.
          </Section>

          <Section title="Not financial advice">
            Signals are shared for information and education only. They aren&apos;t investment,
            financial or trading advice. Futures trading carries a high risk of loss, and past
            results don&apos;t predict future ones.
          </Section>

          <Section title="Changes">
            If this policy changes, we&apos;ll update this page and the date above.
          </Section>

          <Section title="Contact">
            Questions about privacy? Contact the developer through the email listed on our Google
            Play store page.
          </Section>
        </div>
      </article>
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-2 text-xl font-semibold">{title}</h2>
      <div className="text-muted">{children}</div>
    </section>
  );
}
