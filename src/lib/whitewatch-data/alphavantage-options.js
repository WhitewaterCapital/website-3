import "server-only";

// ═══════════════════════════════════════════════════════════════════════════
// Alpha Vantage options-chain adapter — REPLACES the Tradier-sandbox
// integration (see git history / the deleted tradier-sandbox.js) after the
// fund's owner discovered mid-signup that Tradier's sandbox now requires
// full identity verification (tax ID, government ID) to even generate a
// token — a much higher bar than the 2014 blog post ("no brokerage account
// required") that this platform's earlier research had relied on. The owner
// chose to switch to Alpha Vantage's free tier instead: no identity
// verification, just an email address, at the cost of a MUCH tighter rate
// limit (documented by Alpha Vantage's own support page, fetched 2026-09-13,
// as "25 API requests per day"; several independent third-party reviews
// dated 2026 additionally state "5 requests per minute", though that
// specific number was not found directly quoted on an Alpha Vantage-owned
// page during this research — treated below as corroborated-but-not-
// primary-sourced).
//
// WHAT WAS VERIFIED, AND HOW (read this before trusting anything below): this
// sandbox has NO outbound network access to www.alphavantage.co — a direct
// `fetch()` from this environment returns a bare 403 from the local egress
// proxy before any request reaches the internet. Every fact below therefore
// comes from the WebSearch/WebFetch tools (which reach the real internet
// through Anthropic's own infrastructure, not this sandbox's egress proxy),
// fetched/searched 2026-09-13 — NOT from training-data memory, and NOT from
// an actual authenticated call to Alpha Vantage's options endpoints (no real
// API key was available to this session either). This adapter has never
// made a real HTTP call. The fund's owner must exercise it against a real
// free-tier key before trusting it in production; until then, treat this as
// "built correctly against the best-available evidence, defensively coded
// for the cases that evidence couldn't settle — not yet proven end-to-end."
//
// ── THE QUESTION THIS TASK FLAGGED AS GENUINELY AMBIGUOUS: does
// HISTORICAL_OPTIONS (or REALTIME_OPTIONS) actually work on Alpha Vantage's
// FREE tier, or is it gated behind a paid "premium" plan? ──────────────────
// Short answer: it could not be settled with certainty from public sources
// as of 2026-09-13, and the evidence leans — but does not conclusively
// prove — toward "gated, or at least likely to become gated." Specifically:
//
//   AGAINST free-tier access (the more numerous and more recent sources):
//   - Alpha Vantage's OWN premium-plan page (alphavantage.co/premium/,
//     fetched directly) states that premium subscribers get "realtime US
//     market data, 15-minute delayed US market data, realtime US options
//     data" — i.e. Alpha Vantage's own marketing copy lists realtime
//     options data as a premium perk. It does not explicitly say historical
//     options is free, but it also doesn't say it isn't.
//   - Three independently-run, 2026-dated third-party review sites
//     (alphalog.ai, findmymoat.com, tradingtoolshub.com — none affiliated
//     with each other as far as could be determined) each state, in their
//     own words, that BOTH end-of-day/historical options data AND realtime
//     options data require a PAID plan: end-of-day/historical options
//     starting at the "Standard" $49.99/mo tier, realtime options only at
//     the $199.99/mo tier and above.
//   - Alpha Vantage has a documented history of moving previously-free
//     endpoints behind "premium" gates without much fanfare: a 2023 GitHub
//     issue (portfolio-performance/portfolio#3275) shows TIME_SERIES_DAILY
//     — for years a bog-standard free endpoint — started returning `{
//     "Information": "Thank you for using Alpha Vantage! This is a premium
//     endpoint. You may subscribe to any of the premium plans at
//     https://www.alphavantage.co/premium/ to instantly unlock all premium
//     endpoints" }` for free-tier keys. This is direct evidence of the
//     EXACT error shape a plan-gated endpoint returns, and it establishes
//     that "used to be free, isn't anymore" is a real, precedented pattern
//     for this vendor — precisely the mistake this whole task exists to
//     avoid repeating (cf. the stale 2014 Tradier blog post).
//
//   FOR free-tier access (a single, older, harder-to-date source):
//   - A third-party MCP server's README (github.com/berlinbra/
//     alpha-vantage-mcp) states the opposite for HISTORICAL_OPTIONS
//     specifically: "get-historical-options... works with all API key
//     tiers" including free, and that only REALTIME_OPTIONS needs the
//     600/1200-req/min premium tier (free/standard keys get "placeholder/
//     demo data" instead of an error for that one). No publish/verification
//     date could be confirmed for this claim, and given Alpha Vantage's
//     documented history of tightening the free tier over time (see
//     TIME_SERIES_DAILY above), an undated claim that a specific endpoint
//     is still free cannot be weighted as strongly as three convergent
//     2026-dated sources saying otherwise.
//
// CONCLUSION: genuinely uncertain, leaning toward "likely gated," but this
// module does NOT resolve that uncertainty by assumption. It calls
// HISTORICAL_OPTIONS for real (never REALTIME_OPTIONS — every source that
// mentions it agrees that one needs at least the $199.99/mo tier, so it
// isn't worth spending any of a 25-request daily budget probing it) and
// CLASSIFIES whatever comes back into one of three fundamentally different
// buckets — real data, permanently-plan-gated, or temporarily-rate-limited
// — never collapsing the last two into one generic "error", per this task's
// explicit requirement. Whichever bucket a real key actually lands in
// becomes visible to the fund's owner immediately, honestly, the first time
// they use this — see `classifyAlphaVantageResponse` below.
//
// ── SIGNUP (verified directly against alphavantage.co/support/#api-key,
// fetched 2026-09-13) ────────────────────────────────────────────────────
// "Claim your free key ... with lifetime access" at
// https://www.alphavantage.co/support/#api-key — just an email address and
// a one-line "what best describes you" selection, no payment method, no
// identity verification of any kind. This is the real contrast with
// Tradier: genuinely no-friction signup, at the cost of the endpoint-gating
// uncertainty documented above and a much tighter request budget either way.
//
// ── FIELD SCHEMA (options chain) — CROSS-CHECKED, NOT DIRECTLY QUOTED FROM
// ALPHA VANTAGE'S OWN DOCS ───────────────────────────────────────────────
// Alpha Vantage's own documentation page (alphavantage.co/documentation/)
// is a single very large page; the fetch tool available to this session
// could not retrieve the fully-rendered Options Data APIs section of it
// (it repeatedly cut off before that section). The per-contract field list
// below is therefore reconstructed from THIRD-PARTY sources (a technical
// blog post cross-checked against the berlinbra MCP server's own tool
// schema, which independently lists an overlapping field set) rather than
// quoted verbatim from Alpha Vantage itself — flagged here exactly the way
// tradier-sandbox.js flagged its own INFERRED wrapper-key guess, so nobody
// mistakes this for a verified fact:
//   per-contract fields (used ones only): contractID, symbol, expiration,
//     strike, type ("call"|"put"), bid, ask, volume, open_interest,
//     implied_volatility, delta, gamma, theta, vega, date (the trading day
//     this specific row reflects — see the "data freshness" note below)
//   envelope (RECONSTRUCTED, not directly observed): { "endpoint": "...",
//     "message": "success", "data": [ {...contract...}, ... ] } — this
//     module's parser checks for this shape but falls back to a couple of
//     other plausible shapes and returns an EMPTY array (never a crash,
//     never a fabricated contract) if nothing matches, exactly like
//     tradier-sandbox.js's old extractContractsFromResponse did.
//   NOTE: Alpha Vantage's schema exposes a single `implied_volatility` per
//     contract, not Tradier/ORATS' separate bid_iv/mid_iv/ask_iv trio. This
//     module maps it to `greeks.mid_iv` (the field options-summary.js's
//     math actually reads) and leaves bid_iv/ask_iv honestly null rather
//     than inventing a bid/ask spread on IV that Alpha Vantage never gave.
//
// ── DATA FRESHNESS — DELIBERATELY NOT CLAIMING A DELAY NUMBER ───────────
// tradier-sandbox.js could quote Tradier's own docs verbatim for an exact
// "15 minutes delayed" figure. No equivalently explicit, directly-quoted
// freshness figure for HISTORICAL_OPTIONS could be found for Alpha Vantage
// in this research pass (again: the docs page's relevant section did not
// render for the fetch tool). What IS clear from every source consulted is
// that HISTORICAL_OPTIONS is described as an end-of-day / historical
// dataset — a snapshot as of a specific trading day, returned as a `date`
// field on the response itself — not a live intraday feed (REALTIME_OPTIONS
// is Alpha Vantage's real-time product, and it is the one gated behind the
// $199.99+/mo tier per every source that addresses it). Rather than guess
// a specific number of minutes/hours of staleness the way it would be
// tempting to copy from the Tradier file, this module surfaces the actual
// `date` field from the response and lets the UI say "as of <that date>" —
// a true statement regardless of exactly how stale that date turns out to
// be relative to "now".
//
// ── WHY THIS MODULE MAKES AT MOST TWO REAL CALLS, AND IN THIS ORDER ──────
// With a 25-request/day budget, every call matters. HISTORICAL_OPTIONS is
// called FIRST and alone. GLOBAL_QUOTE (for the underlying's spot price,
// needed to pick the ATM strike — the options-chain payload does not appear
// to carry the underlying's own price anywhere in the per-contract fields
// listed above) is only called SECOND, and only if the options call itself
// came back as real usable data — never spent probing a call that's about
// to be reported as not_configured/plan_gated/rate_limited/no-listed-
// options anyway. GLOBAL_QUOTE is one of Alpha Vantage's original,
// long-documented free-tier functions (used in Alpha Vantage's own "demo"
// API-key example across many third-party integration guides); no source
// found during this research flagged it as premium-gated, unlike the
// options endpoints — but see the same "not directly re-confirmed against
// Alpha Vantage's own docs page in this pass" caveat as above.
// ═══════════════════════════════════════════════════════════════════════════

const BASE = "https://www.alphavantage.co/query";
const _TIMEOUT_MS = 15000;
// Free tier is documented (see header) around 5 requests/minute, 25/day.
// This in-process throttle only protects a single server instance against
// itself — it can't see calls from other instances/deploys — so treat it as
// a courtesy floor, not a guarantee. 12.5s clears "5/min" with real margin.
const _MIN_INTERVAL_MS = 12500;

// Matches data-router/router/adapters/alpha_vantage.py's REQUIRED_ENV_VAR
// name for the same vendor (a separate, unrelated Python subsystem — see
// that file — but there is no reason for this one vendor's key to have two
// different env var spellings across this codebase).
const ENV_VAR = "ALPHA_VANTAGE_API_KEY";

export function alphaVantageKey() {
  const k = (process.env[ENV_VAR] || "").trim();
  if (!k) {
    throw new Error(
      `${ENV_VAR} is not set. Get a free key (no identity verification, ` +
        "just an email address) at https://www.alphavantage.co/support/#api-key " +
        `— then put it in .env.local as ${ENV_VAR}=your_key`
    );
  }
  return k;
}

// Cheap presence check for callers (the API route) that want to render an
// honest "not configured" state instead of letting the throw above surface
// as a 500.
export function isAlphaVantageConfigured() {
  return Boolean((process.env[ENV_VAR] || "").trim());
}

let _lastRequestAt = 0;
async function _throttle() {
  const gap = Date.now() - _lastRequestAt;
  if (gap < _MIN_INTERVAL_MS) {
    await new Promise((r) => setTimeout(r, _MIN_INTERVAL_MS - gap));
  }
  _lastRequestAt = Date.now();
}

async function _get(fn, params) {
  await _throttle();
  const url = new URL(BASE);
  url.searchParams.set("function", fn);
  url.searchParams.set("apikey", alphaVantageKey());
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
  }
  const resp = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(_TIMEOUT_MS),
  });
  if (!resp.ok) {
    throw new Error(`Alpha Vantage HTTP error ${resp.status} for function=${fn}`);
  }
  return resp.json();
}

// --- Response classification -------------------------------------------
//
// Alpha Vantage's own JSON error shapes (per the header's research writeup
// and the directly-quoted premium-endpoint message from the 2023 GitHub
// issue) are ambiguous enough — and drift in wording over time enough, per
// that same vendor's own track record — that this classifies by KEYWORD,
// not by exact string equality. That is a deliberate defensive choice: a
// slightly-reworded future message still gets bucketed correctly instead of
// falling through to a generic, less-informative "error". This function is
// pure (no I/O) specifically so scripts/verify-options.mjs can exercise it
// against constructed payloads without a live call.
//
// Returns one of:
//   { kind: "data", data: <the parsed array of contract rows> }
//   { kind: "empty" } — a syntactically valid "success" response with a
//     present-but-empty data array (Alpha Vantage's own way, if this
//     inference is right, of saying "no options chain for this symbol");
//     see the header note that this specific inference was not confirmed
//     against a real empty-array example, so getOptionsSnapshot treats it
//     as "not_applicable" but says so honestly rather than as a fact.
//   { kind: "plan_gated", message } — this endpoint is not on the caller's
//     plan; retrying will NEVER work without upgrading. Distinct from...
//   { kind: "rate_limited", message } — the caller's plan CAN reach this
//     endpoint but has hit its request-frequency ceiling for now; retrying
//     later (next minute, or next UTC day) may work.
//   { kind: "error", message } — a genuine malformed-request/unrecognized
//     response case (bad symbol, Alpha Vantage `Error Message` field, or a
//     response shape this parser doesn't recognize at all).
export function classifyAlphaVantageResponse(json) {
  if (!json || typeof json !== "object") {
    return { kind: "error", message: "Alpha Vantage returned a non-JSON-object response." };
  }

  if (typeof json["Error Message"] === "string") {
    return { kind: "error", message: json["Error Message"] };
  }

  // Alpha Vantage has used both "Note" (historically, for per-minute call
  // frequency) and "Information" (more recently, seen for both daily-limit
  // AND plan-gating messages) as the wrapper key for a non-data response.
  // Since the KEY alone doesn't reliably distinguish the two situations
  // this task requires distinguishing, this checks the MESSAGE TEXT instead.
  const infoText = typeof json["Information"] === "string" ? json["Information"] : null;
  const noteText = typeof json["Note"] === "string" ? json["Note"] : null;
  const text = infoText ?? noteText;

  if (text) {
    const lower = text.toLowerCase();
    // Directly matches the wording quoted verbatim in the 2023
    // TIME_SERIES_DAILY premium-gating GitHub issue cited in this file's
    // header — checked BEFORE the rate-limit branch below because a
    // plan-gating message can also happen to mention "premium plans",
    // which the rate-limit branch's looser matching would otherwise catch.
    if (lower.includes("premium endpoint") || lower.includes("this endpoint is not available")) {
      return { kind: "plan_gated", message: text };
    }
    if (
      lower.includes("requests per day") ||
      lower.includes("rate limit") ||
      lower.includes("call frequency") ||
      lower.includes("calls per minute") ||
      lower.includes("standard api")
    ) {
      return { kind: "rate_limited", message: text };
    }
    // An "Information"/"Note" message that matched neither known pattern:
    // do NOT guess which bucket it belongs in. Surface it verbatim as a
    // generic error so a human can read Alpha Vantage's own words rather
    // than have this code silently miscategorize a message it doesn't
    // recognize (e.g. a future wording change from Alpha Vantage).
    return { kind: "error", message: text };
  }

  if (Array.isArray(json.data)) {
    return json.data.length === 0 ? { kind: "empty" } : { kind: "data", data: json.data };
  }

  return { kind: "error", message: "Alpha Vantage response had no recognized data/Information/Note/Error Message field." };
}

// --- Expirations -----------------------------------------------------------
// Same "standard monthly, else nearest available" convention as the old
// Tradier adapter (see the deleted tradier-sandbox.js in git history) —
// this is a fact about the Gregorian calendar and about which expiration is
// most liquid/most-quoted, neither of which depends on which vendor's API
// supplied the raw chain.

function isThirdFriday(isoDate) {
  const d = new Date(isoDate + "T00:00:00Z");
  const dayOfWeek = d.getUTCDay();
  const dayOfMonth = d.getUTCDate();
  return dayOfWeek === 5 && dayOfMonth >= 15 && dayOfMonth <= 21;
}

export function pickExpiration(dates, todayISO) {
  const future = dates.filter((d) => d >= todayISO).sort();
  if (future.length === 0) return null;
  const monthlies = future.filter(isThirdFriday);
  if (monthlies.length > 0) {
    return { date: monthlies[0], basis: "standard-monthly" };
  }
  return { date: future[0], basis: "nearest-available" };
}

// --- Contract parsing --------------------------------------------------

function parseGreeks(raw) {
  const num = (x) => (Number.isFinite(Number(x)) ? Number(x) : null);
  const midIv = num(raw.implied_volatility);
  const delta = num(raw.delta);
  const gamma = num(raw.gamma);
  const theta = num(raw.theta);
  const vega = num(raw.vega);
  if (midIv == null && delta == null && gamma == null && theta == null && vega == null) return null;
  // bid_iv/ask_iv are honestly null: Alpha Vantage's schema (per the header's
  // cross-checked field list) exposes one implied_volatility per contract,
  // not a separate bid/ask-side IV the way Tradier/ORATS did.
  return { delta, gamma, theta, vega, mid_iv: midIv, bid_iv: null, ask_iv: null };
}

// Skips malformed rows rather than crash or fabricate a value for them —
// same discipline the old Tradier adapter used (see tradier-sandbox.js in
// git history) and prices_tiingo.py's fetch_prices uses for malformed rows.
function parseContract(raw) {
  try {
    if (!raw || typeof raw !== "object") return null;
    const strike = Number(raw.strike);
    const optionType = String(raw.type ?? "").toLowerCase();
    if (!Number.isFinite(strike) || (optionType !== "call" && optionType !== "put")) {
      return null;
    }
    return {
      symbol: String(raw.contractID ?? raw.symbol ?? ""),
      strike,
      optionType,
      bid: Number.isFinite(Number(raw.bid)) ? Number(raw.bid) : null,
      ask: Number.isFinite(Number(raw.ask)) ? Number(raw.ask) : null,
      openInterest: Number.isFinite(Number(raw.open_interest)) ? Number(raw.open_interest) : null,
      volume: Number.isFinite(Number(raw.volume)) ? Number(raw.volume) : null,
      expiration: typeof raw.expiration === "string" ? raw.expiration : null,
      quoteDate: typeof raw.date === "string" ? raw.date : null,
      greeks: parseGreeks(raw),
    };
  } catch {
    return null;
  }
}

// --- Underlying spot price -----------------------------------------------

export function parseGlobalQuoteLast(json) {
  const quote = json?.["Global Quote"];
  const last = Number(quote?.["05. price"]);
  return Number.isFinite(last) && last > 0 ? last : null;
}

export async function getUnderlyingLast(symbol) {
  const data = await _get("GLOBAL_QUOTE", { symbol });
  const cls = classifyAlphaVantageResponse(
    // GLOBAL_QUOTE's own success shape doesn't have a `data` array (it has
    // "Global Quote"), so reuse the same rate-limit/plan-gated/error text
    // detection by handing classify the same object — its Array.isArray(
    // json.data) branch simply won't match and it'll fall to the generic
    // "no recognized field" error, which getUnderlyingLast maps to `null`
    // below rather than surfacing a second, confusing status for the one
    // ancillary spot-price call.
    data
  );
  if (cls.kind === "plan_gated" || cls.kind === "rate_limited" || cls.kind === "error") {
    // Don't fail the whole snapshot over the spot-price call specifically —
    // getOptionsSnapshot below decides what an unresolvable spot means
    // (honest "no_data", never a fabricated price).
    return null;
  }
  return parseGlobalQuoteLast(data);
}

// --- Orchestration: one ticker -> a raw snapshot ----------------------------
//
// Returns a discriminated `status`, never a fabricated number. Mirrors the
// old Tradier adapter's status set plus the two NEW states this task
// requires so a plan-gating rejection is never shown as if it were the same
// thing as a temporary rate limit, or as a generic crash:
//   "plan_gated"    — Alpha Vantage says this endpoint isn't on this key's
//                      plan. Retrying will not help without upgrading.
//   "rate_limited"  — Alpha Vantage says the free tier's request budget
//                      (frequency and/or daily) is exhausted right now.
//                      Retrying later may work.
//   "not_applicable"— a real "success" response came back with zero
//                      contracts — see classifyAlphaVantageResponse's
//                      "empty" kind and its header caveat about this
//                      specific inference not being independently confirmed.
//   "no_data"       — contracts came back but no usable expiration/spot
//                      could be resolved from them.
//   "ok"            — a usable chain with a resolvable spot price.
// A genuine fetch/timeout/auth failure is not caught here — it propagates
// so the API route can label it "error", distinct from both of the above.
export async function getOptionsSnapshot(symbol) {
  const todayISO = new Date().toISOString().slice(0, 10);
  const raw = await _get("HISTORICAL_OPTIONS", { symbol });
  const cls = classifyAlphaVantageResponse(raw);

  if (cls.kind === "plan_gated") {
    return { status: "plan_gated", symbol, asOf: new Date().toISOString(), reason: cls.message };
  }
  if (cls.kind === "rate_limited") {
    return { status: "rate_limited", symbol, asOf: new Date().toISOString(), reason: cls.message };
  }
  if (cls.kind === "error") {
    throw new Error(cls.message);
  }
  if (cls.kind === "empty") {
    return { status: "not_applicable", symbol, asOf: new Date().toISOString() };
  }

  const contracts = cls.data.map(parseContract).filter((c) => c !== null);
  if (contracts.length === 0) {
    return { status: "no_data", symbol, asOf: new Date().toISOString(), reason: "Chain response had rows but none parsed into a usable call/put contract." };
  }

  const quoteDate = contracts.find((c) => c.quoteDate)?.quoteDate ?? null;
  const dates = Array.from(new Set(contracts.map((c) => c.expiration).filter(Boolean)));
  const picked = pickExpiration(dates, todayISO);
  if (!picked) {
    return { status: "not_applicable", symbol, asOf: new Date().toISOString() };
  }

  const chainForExpiration = contracts.filter((c) => c.expiration === picked.date);
  const spot = await getUnderlyingLast(symbol);

  if (chainForExpiration.length === 0 || spot == null) {
    return {
      status: "no_data",
      symbol,
      asOf: new Date().toISOString(),
      quoteDate,
      expiration: picked.date,
      expirationBasis: picked.basis,
      reason: spot == null ? "Options chain came back but the underlying's spot price (GLOBAL_QUOTE) could not be resolved this pull." : undefined,
    };
  }

  return {
    status: "ok",
    symbol,
    asOf: new Date().toISOString(),
    quoteDate,
    expiration: picked.date,
    expirationBasis: picked.basis,
    spot,
    contracts: chainForExpiration,
  };
}
