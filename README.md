# Four & Co. — Investment Club Platform

A website for a small (4-member) investment club that pools capital into one
account: a **public track-record page** anyone can see, and a **members-only
portal** with the full picture.

> Currently runs on **sample data** so you can see everything working. The
> broker (Interactive Brokers) and a database plug in at marked seams — nothing
> in the UI or the math changes when you do.

## Run it

```bash
npm run dev
```

- `/` — public track record: equity curve vs SPY, return, exposure gauge. **No tickers or holdings.**
- `/dashboard` — members: positions, P&L, risk metrics, activity _(passcode gate)_
- `/members` — unit accounting: who owns what, contribution history
- `/proposals` — trade ideas + voting

Members area passcode defaults to `letmein` (set `MEMBER_PASSCODE` to change).

## How it's organized

```
src/
  app/                 pages + API routes
    page.tsx           public track record
    dashboard/         members dashboard
    members/           unit accounting
    proposals/         proposals + voting
    api/               login, logout, cron snapshot
  components/          Nav, charts (dependency-free SVG), UI bits
  lib/
    types.ts           the domain model
    sample-data.ts     seed data (swap for a DB)
    units.ts           unit accounting — the fair way to share one pool
    metrics.ts         return, drawdown, volatility, Sharpe, exposure
    broker/            broker adapter: interface + Mock + IBKR stub
  proxy.ts             auth gate for members routes
```

## The two pieces that make it a *club* tool

- **Unit accounting** (`lib/units.ts`) — everyone owns *units* like shares of a
  tiny fund. Contributions buy units at that day's unit value, so deposits and
  withdrawals at different times stay fair. This is the thing clubs get wrong.
- **Proposals + voting** (`/proposals`) — shared capital means shared decisions,
  with the thesis logged for later review.

## Going to production — the seams

1. **Broker (Interactive Brokers).** Implement `src/lib/broker/ibkr.ts` against
   the IBKR Client Portal Web API, then set `BROKER=ibkr`, `IBKR_GATEWAY_URL`,
   and `IBKR_ACCOUNT_ID`. Everything else already talks to the adapter, not IBKR.
2. **Database.** Replace `src/lib/sample-data.ts` reads with a real DB
   (Postgres / Supabase). Tables mirror `types.ts`: members, contributions,
   snapshots, positions, proposals, votes, trades.
3. **Real auth.** The shared passcode in `src/lib/auth.ts` is a placeholder.
   Swap for per-member auth (Clerk / Auth.js / Supabase) for real logins + roles.
4. **Snapshots.** `api/cron/snapshot` runs on a Vercel Cron (`vercel.json`);
   have it insert a row each run so the equity curve builds real history.

## Before real money

Talk to a CPA/attorney about forming an **LLC** with an operating agreement and
opening an **entity brokerage account** (not sharing a personal login). This is
the standard "investment club" structure. Nothing here is investment advice.
