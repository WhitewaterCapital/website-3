import "server-only";

// ═══════════════════════════════════════════════════════════════════════════
// Tradier SANDBOX options-chain adapter — the site's first real (not
// synthetic) options/implied-volatility data source.
//
// Why Tradier sandbox: the fund's owner chose it deliberately over paying for
// a real-time options vendor right now. It is a genuinely free developer
// account (verified 2026-09 against Tradier's own docs — see citations below)
// that returns REAL options-chain quotes with greeks/IV sourced from ORATS,
// 15 minutes delayed. This is the same "free, keyed, real data with an
// honestly-documented limitation" pattern this codebase already uses for
// Tiingo prices (see intra-exitus-engine/ie/adapters/prices_tiingo.py) — the
// two adapters share no code, by design, matching that file's own note about
// engines not sharing adapter code.
//
// WHAT WAS VERIFIED LIVE VS. WHAT COULD NOT BE (read this before trusting a
// field name below): this sandbox has NO outbound network access to
// sandbox.tradier.com — confirmed by a direct connection attempt during
// development, which the environment's proxy rejected at the policy layer
// (CONNECT rejected, 403). Every fact and field name below therefore comes
// from Tradier's OWN current documentation (docs.tradier.com, fetched
// 2026-09-13) and, where the docs page itself didn't render a JSON example,
// from a worked example on a third-party Tradier API tutorial + a published
// Go client's field-level struct (both cross-checked against each other and
// against the docs' own field list for consistency) — NOT from training-data
// memory. This adapter has never made a real HTTP call. The fund's owner (or
// a networked CI run) must exercise this against a real sandbox token before
// trusting it in production; until then, treat this as "built correctly
// against the documented contract, not yet proven end-to-end."
//
// VERIFIED DIRECTLY (quoted from docs.tradier.com/docs/faq and
// docs.tradier.com/docs/rate-limiting, 2026-09-13):
//   - Sandbox base URL: "the prefix sandbox.tradier.com/v1 with any endpoint"
//   - Delay: "We delay our market data the industry standard 15-minutes for
//     all sandbox data."
//   - Redistribution/ToS (the load-bearing constraint — quote this accurately
//     anywhere this data reaches a member, matching how prices_tiingo.py's
//     own docstring quotes Tiingo's terms): "Unless you are a Tradier
//     Partner, Tradier APIs are entitled for personal use only." The fund is
//     not a Tradier Partner, so this data may not be redistributed outside
//     the fund's own internal member platform — it must never be resold,
//     piped to a public feed, or otherwise handed to anyone who isn't
//     using it here, on this platform, for the fund's own trade decisions.
//   - Rate limit: "Sandbox: 60 request per minute" for market-data endpoints
//     (half production's 120/min).
//   - Free developer signup, no funded brokerage account: confirmed via
//     Tradier's own getting-started guide ("You'll get access to both live
//     trading and our paper trading sandbox environment") and Tradier's 2014
//     sandbox-launch announcement, which is explicit: "Free developer access
//     (no brokerage account required)." Sign up at
//     https://developer.tradier.com/user/sign_up (or tradier.com generally),
//     then generate a SANDBOX token at https://web.tradier.com/user/api —
//     no card, no funding, no approval wait.
//   - Greeks/IV are sourced from ORATS and (per a Tradier API walkthrough)
//     "updated once every hour" — i.e. even within one sandbox pull, greeks
//     can be up to an hour stale on top of the 15-minute quote delay. Both
//     lags are stated explicitly in the always-visible UI caveat banner on
//     OptionsPanel (src/components/panels/ModelPanels.tsx) — not just here
//     in a code comment — per this task's requirement that a member sizing
//     a real trade off this data sees the caveat where they'll read it.
//
// VERIFIED FIELD-LEVEL SCHEMA (options chain, from
// docs.tradier.com/reference/brokerage-api-markets-get-options-chains and
// cross-checked against a worked AAPL-put example on a third-party Tradier
// API tutorial, and against a published Go Tradier client's Quote struct for
// the shared price fields):
//   endpoint: GET /v1/markets/options/chains?symbol=X&expiration=YYYY-MM-DD&greeks=true
//   per-contract fields (used ones only): symbol, strike, bid, ask, last,
//     volume, open_interest, option_type ("call"|"put"), expiration_date
//   nested greeks object (present only when greeks=true and ORATS has a
//     value): delta, gamma, theta, vega, rho, phi, bid_iv, mid_iv, ask_iv,
//     smv_vol, updated_at
//   real example quoted verbatim from the tutorial (AAPL put):
//     { "symbol": "AAPL211126P00075000", "strike": 75.0, "bid": 0.0,
//       "ask": 0.01, "greeks": { "delta": 0.0, "gamma": 7.73678E-15,
//       "theta": -1.02738E-4, "vega": 2.0E-5, "mid_iv": 0.71214,
//       "smv_vol": 0.398, "updated_at": "2021-11-16 20:56:02" },
//       "open_interest": 7, "option_type": "put" }
//
// VERIFIED FIELD-LEVEL SCHEMA (expirations, from
// docs.tradier.com/reference/brokerage-api-markets-get-options-expirations,
// example quoted verbatim from the same tutorial):
//   endpoint: GET /v1/markets/options/expirations?symbol=X
//   response: { "expirations": { "date": ["2021-11-19", "2021-11-26", ...] } }
//   (Tradier's own docs page for this endpoint additionally documents an
//   `expirationType` query flag that would nest a "standard"/"weekly"
//   classification per date, but did not render a JSON example of that
//   shape — this adapter deliberately does NOT depend on that unverified
//   nesting; see `pickExpiration` below for how "standard monthly" is
//   instead computed independently, from the plain date list.)
//
// VERIFIED FIELD-LEVEL SCHEMA (quotes, for the underlying's spot price, from
// docs.tradier.com/reference/brokerage-api-markets-get-quotes plus a
// published Go client's Quote struct, cross-checked against a worked
// example):
//   endpoint: GET /v1/markets/quotes?symbols=X
//   response: { "quotes": { "quote": { "symbol": "AAPL", "last": 170.00, ... } } }
//   (Tradier is documented elsewhere to return a bare object, not a
//   single-element array, when exactly one symbol is requested — this
//   adapter normalizes both shapes defensively rather than assume one.)
//
// INFERRED, NOT DIRECTLY QUOTED (flagged so nobody mistakes this for a
// verified fact): the options-chain endpoint's own top-level wrapper key.
// Every other Tradier market-data endpoint this module touches wraps its
// array in `{ <plural>: { <singular>: [...] } }` (expirations -> date,
// quotes -> quote) so `{ "options": { "option": [...] } }` is inferred by
// that same, consistent convention — but no fetched page rendered a full
// chains response to quote directly. `extractContractsFromResponse` below
// therefore does not trust this shape blindly: it checks for it, falls back
// to a couple of other plausible shapes, and — if nothing matches — returns
// an EMPTY array rather than throwing or fabricating contracts. A symbol
// whose options endpoint 200s with a shape this parser doesn't recognize
// will show up to the member as "no usable options data" (status
// "no_data"), never as a crash and never as invented numbers.
// ═══════════════════════════════════════════════════════════════════════════

const SANDBOX_BASE = "https://sandbox.tradier.com/v1";
const _TIMEOUT_MS = 15000;
// Sandbox market-data limit is documented as 60 req/min = 1 per second.
// Leaving real headroom (this module makes up to 3 calls per ticker: quote +
// expirations + chain) so a few members hitting the Ticker Hub back-to-back
// don't trip Tradier's own limiter.
const _MIN_INTERVAL_MS = 350;

export function tradierKey() {
  const k = (process.env.TRADIER_API_KEY || "").trim();
  if (!k) {
    throw new Error(
      "TRADIER_API_KEY is not set. Get a free SANDBOX token (no funded " +
        "brokerage account required) by signing up at " +
        "https://developer.tradier.com/user/sign_up, then generating a " +
        "Sandbox token at https://web.tradier.com/user/api — then put it in " +
        ".env.local as TRADIER_API_KEY=your_sandbox_token"
    );
  }
  return k;
}

// Cheap presence check for callers (the API route) that want to render an
// honest "not configured" state instead of letting the RuntimeError-style
// throw above surface as a 500.
export function isTradierConfigured() {
  return Boolean((process.env.TRADIER_API_KEY || "").trim());
}

let _lastRequestAt = 0;
async function _throttle() {
  const gap = Date.now() - _lastRequestAt;
  if (gap < _MIN_INTERVAL_MS) {
    await new Promise((r) => setTimeout(r, _MIN_INTERVAL_MS - gap));
  }
  _lastRequestAt = Date.now();
}

async function _get(path, params) {
  await _throttle();
  const url = new URL(SANDBOX_BASE + path);
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
  }
  const resp = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${tradierKey()}`,
      Accept: "application/json",
    },
    signal: AbortSignal.timeout(_TIMEOUT_MS),
  });
  if (resp.status === 401) {
    throw new Error(
      "Tradier sandbox rejected the API key (401) — check TRADIER_API_KEY " +
        "is a valid SANDBOX token generated at https://web.tradier.com/user/api"
    );
  }
  if (!resp.ok) {
    throw new Error(`Tradier sandbox API error ${resp.status} for ${path}`);
  }
  return resp.json();
}

// --- Expirations -----------------------------------------------------------

// Normalizes Tradier's known "bare value instead of one-element array" quirk
// (documented behavior across this API family — see the quotes example
// above) so callers never have to special-case it.
function asArray(x) {
  if (x == null) return [];
  return Array.isArray(x) ? x : [x];
}

export async function getExpirations(symbol) {
  const data = await _get("/markets/options/expirations", { symbol });
  const dates = data?.expirations?.date;
  if (!dates) return []; // Tradier returns `"expirations": null` for a
  // symbol with no listed options at all — a normal, expected case (most
  // tickers have no options), not an error.
  return asArray(dates).filter((d) => typeof d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(d));
}

// "Standard monthly" = expires the 3rd Friday of its month, the long-standing
// convention for US equity/index monthly option series. Computed directly
// from the calendar rather than trusted from an unverified Tradier
// `expiration_type` field (see the file header's INFERRED note) — this is a
// fact about the Gregorian calendar, not about Tradier's response shape, so
// it can't be wrong because a field name was guessed.
function isThirdFriday(isoDate) {
  const d = new Date(isoDate + "T00:00:00Z");
  const dayOfWeek = d.getUTCDay(); // 0=Sun .. 6=Sat
  const dayOfMonth = d.getUTCDate();
  return dayOfWeek === 5 && dayOfMonth >= 15 && dayOfMonth <= 21;
}

// Picks the nearest expiration to use for the "expected move" read.
// Documented choice: prefer the nearest STANDARD MONTHLY expiration (the
// deepest, most liquid, most-quoted series for most underlyings) over the
// nearest weekly, because ORATS' greeks/IV computation is more reliable on
// the more liquid monthly chain. Falls back to the nearest available
// expiration of ANY type when the returned list has no standard monthly in
// it (common for names that only list weeklies, or a short returned list) —
// and always reports which basis was actually used (`expirationBasis`) so
// the UI/report never silently mixes the two without saying so.
export function pickExpiration(dates, todayISO) {
  const future = dates.filter((d) => d >= todayISO).sort();
  if (future.length === 0) return null;
  const monthlies = future.filter(isThirdFriday);
  if (monthlies.length > 0) {
    return { date: monthlies[0], basis: "standard-monthly" };
  }
  return { date: future[0], basis: "nearest-available" };
}

// --- Underlying spot price ---------------------------------------------------

export async function getUnderlyingLast(symbol) {
  const data = await _get("/markets/quotes", { symbols: symbol });
  const quote = data?.quotes?.quote;
  if (!quote) return null; // e.g. an invalid/delisted symbol
  const q = Array.isArray(quote) ? quote[0] : quote;
  const last = Number(q?.last);
  return Number.isFinite(last) && last > 0 ? last : null;
}

// --- Options chain -----------------------------------------------------------

function parseGreeks(g) {
  if (!g || typeof g !== "object") return null;
  const num = (x) => (Number.isFinite(Number(x)) ? Number(x) : null);
  return {
    delta: num(g.delta),
    gamma: num(g.gamma),
    theta: num(g.theta),
    vega: num(g.vega),
    mid_iv: num(g.mid_iv),
    bid_iv: num(g.bid_iv),
    ask_iv: num(g.ask_iv),
  };
}

// Skips malformed contracts rather than crash or fabricate a value for them
// — the exact discipline prices_tiingo.py's fetch_prices uses for malformed
// price rows (try/except KeyError/ValueError/TypeError -> continue).
function parseContract(raw) {
  try {
    const strike = Number(raw.strike);
    const optionType = raw.option_type;
    if (!Number.isFinite(strike) || (optionType !== "call" && optionType !== "put")) {
      return null;
    }
    return {
      symbol: String(raw.symbol ?? ""),
      strike,
      optionType,
      bid: Number.isFinite(Number(raw.bid)) ? Number(raw.bid) : null,
      ask: Number.isFinite(Number(raw.ask)) ? Number(raw.ask) : null,
      openInterest: Number.isFinite(Number(raw.open_interest)) ? Number(raw.open_interest) : null,
      volume: Number.isFinite(Number(raw.volume)) ? Number(raw.volume) : null,
      greeks: parseGreeks(raw.greeks),
    };
  } catch {
    return null;
  }
}

// See the file header's INFERRED note: the wrapper key below is the
// convention-consistent guess, checked defensively with fallbacks, never
// assumed blindly.
function extractContractsFromResponse(data) {
  const candidates = [data?.options?.option, data?.options, data?.option];
  for (const c of candidates) {
    if (c != null) return asArray(c);
  }
  return [];
}

export async function getChain(symbol, expirationDate) {
  const data = await _get("/markets/options/chains", {
    symbol,
    expiration: expirationDate,
    greeks: "true",
  });
  const raw = extractContractsFromResponse(data);
  const contracts = raw.map(parseContract).filter((c) => c !== null);
  return contracts;
}

// --- Orchestration: one ticker -> a raw snapshot ----------------------------

// Fetches everything needed for one ticker. Returns a discriminated
// `status`, never a fabricated number:
//   "not_applicable" — Tradier lists no options at all for this symbol. This
//     is the NORMAL case for most tickers (most stocks, nearly all
//     commodities/FX symbols this platform also covers, have no listed
//     equity options) — shown to members as an informational state, not an
//     error state.
//   "no_data" — options ARE listed, but the chain came back empty/unusable
//     (e.g. a temporarily illiquid/newly-listed series) — also not a crash,
//     but distinct from "not_applicable" because there IS a market here.
//   "ok" — a usable chain with a resolvable spot price came back.
// A genuine fetch/auth/network failure is not caught here — it propagates so
// the API route can label it "error" (a THIRD, distinct state from the two
// honest-abstention states above), per this task's requirement that a
// missing-market abstention must never look like a broken fetch.
export async function getOptionsSnapshot(symbol) {
  const todayISO = new Date().toISOString().slice(0, 10);
  const dates = await getExpirations(symbol);
  if (dates.length === 0) {
    return { status: "not_applicable", symbol, asOf: new Date().toISOString() };
  }

  const picked = pickExpiration(dates, todayISO);
  if (!picked) {
    // All listed expirations are in the past relative to "today" (stale
    // listing) — treat the same as no usable market, not an error.
    return { status: "not_applicable", symbol, asOf: new Date().toISOString() };
  }

  const [contracts, spot] = await Promise.all([
    getChain(symbol, picked.date),
    getUnderlyingLast(symbol),
  ]);

  if (contracts.length === 0 || spot == null) {
    return {
      status: "no_data",
      symbol,
      asOf: new Date().toISOString(),
      expiration: picked.date,
      expirationBasis: picked.basis,
    };
  }

  return {
    status: "ok",
    symbol,
    asOf: new Date().toISOString(),
    expiration: picked.date,
    expirationBasis: picked.basis,
    spot,
    contracts,
  };
}
