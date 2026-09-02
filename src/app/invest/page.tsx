import Link from "next/link";
import { RegisterInterest } from "@/components/RegisterInterest";
import { NewsletterSignup } from "@/components/NewsletterSignup";
import { Card } from "@/components/ui";

export const metadata = {
  title: "Invest — Whitewater",
  description: "Register interest in Whitewater.",
};

// PUBLIC — Investors. A "register interest" page (not a solicitation). Captures
// leads to Supabase so the team can follow up privately once the fund structure
// is in place. Carries a clear not-an-offer disclaimer.
export default function InvestPage() {
  return (
    <div>
      <header className="border-b border-hairline">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <Link href="/" className="text-sm font-semibold uppercase tracking-[0.18em]">
            Whitewater
          </Link>
          <nav className="flex items-center gap-6 text-xs uppercase tracking-[0.12em] text-muted">
            <Link href="/" className="hover:text-foreground">Home</Link>
            <Link href="/dashboard" className="hover:text-foreground">Members</Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-16">
        <p className="font-mono text-sm text-accent">// Investors</p>
        <h1 className="display mt-3 max-w-2xl text-4xl sm:text-5xl">
          Interested in investing alongside us?
        </h1>
        <p className="mt-4 max-w-xl text-muted">
          We&apos;re a concentrated, conviction-led investment club. If you&apos;d
          like to hear more as we open to outside capital, leave your details and
          we&apos;ll reach out personally.
        </p>

        <div className="mt-10 grid gap-10 lg:grid-cols-[1.3fr_1fr]">
          <Card title="Register interest">
            <RegisterInterest />
          </Card>

          <div className="space-y-8">
            <Card title="The letters">
              <p className="text-sm text-foreground/80">
                Our periodic write-ups — theses, positioning, and what we&apos;re
                watching. No spam; unsubscribe anytime.
              </p>
              <div className="mt-4">
                <NewsletterSignup source="invest" />
              </div>
            </Card>
          </div>
        </div>

        <p className="mt-12 border-t border-hairline pt-6 text-xs leading-relaxed text-muted">
          <strong className="text-foreground/70">This is not an offer.</strong>{" "}
          Nothing on this page is an offer to sell or a solicitation to buy any
          security, or investment advice. Any future offering would be private,
          made only through formal documents, and limited to eligible investors.
          Registering interest creates no commitment on either side. Past
          performance is not indicative of future results.
        </p>
      </main>
    </div>
  );
}
