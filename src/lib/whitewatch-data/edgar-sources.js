import 'server-only';

// Live, keyless SEC EDGAR fetch helpers — insider (Form 4) transactions.
//
// THREE real, free, keyless data.sec.gov / www.sec.gov endpoints, no signup,
// no API key exists for any of them:
//   1. https://www.sec.gov/files/company_tickers.json — SEC's own static
//      ticker -> CIK directory, regenerated roughly daily. Verified live
//      2026-09-13 (see note below on HOW — this sandbox itself has no
//      outbound network access to sec.gov, confirmed by a direct curl from
//      this environment returning a 403 policy denial from the local egress
//      proxy; verification instead used the WebFetch tool, which reaches the
//      real internet through Anthropic's own infrastructure rather than this
//      sandbox's org-controlled egress proxy). The live fetch returned real
//      JSON: {"0":{"cik_str":1045810,"ticker":"NVDA","title":"NVIDIA CORP"},
//      "1":{"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."}, ...} —
//      confirmed AAPL -> cik_str 320193 exactly.
//   2. https://data.sec.gov/submissions/CIK##########.json — SEC's own
//      per-filer submissions API. Verified live 2026-09-13 against
//      CIK0000320193 (Apple): real JSON came back (cik, name, tickers,
//      filings.recent...). Crucially, filings.recent lists Form 4 filings
//      for the ISSUER'S own CIK (not just the issuer's own 10-K/8-K/etc) —
//      confirmed by taking the single most-recent filing this endpoint
//      returned for Apple (accession 0001140361-26-036226, filed
//      2026-09-10) and independently fetching that filing's own EDGAR
//      Archives directory, which confirmed it is literally a Form 4 with a
//      primary document named "form4.xml". This is the mechanism this file
//      relies on: an issuer's own submissions.json is a real, free,
//      keyless way to enumerate its insiders' recent Form 4s, without full
//      -text search and without scraping.
//   3. https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/
//      {primaryDocument} — the actual Form 4 XML for one filing. Verified
//      live 2026-09-13 by fetching exactly this URL for the filing found in
//      (2) above; it returned a real ownershipDocument XML for a genuine,
//      dated (2026-09-08) transaction: reporting owner "Jennifer Newstead"
//      (SVP, GC and Government Affairs — an officer), security "Common
//      Stock", transactionCode "S" (open-market sale), 1,438 shares at
//      $317.23/share, disposed, 34,352 shares owned after, direct
//      ownership, with a remark that it was made pursuant to a Rule 10b5-1
//      trading plan. That exact schema shape (ownershipDocument > issuer /
//      reportingOwner / nonDerivativeTable > nonDerivativeTransaction, with
//      most leaf fields wrapped in a <value> element) is what parseXml /
//      parseForm4Xml below are built against.
//
// WHAT THIS FILE DOES NOT ATTEMPT — 13F institutional-ownership trend
// ("which institutions changed their position in ticker X last quarter"):
// researched honestly, and there is NO free, keyless, real-time,
// by-ticker-indexed API for this. What SEC actually offers for 13F is:
//   - Bulk quarterly "Form 13F Data Sets" ZIP files (13f-data-sets page) —
//     structured XML flattened to a few large per-quarter files, updated
//     quarterly, several-month lag, 2-95 MB each — a batch/offline dataset,
//     not a queryable-by-ticker endpoint. There is no per-request "get me
//     everyone who filed a 13F this quarter naming CUSIP X" call.
//   - Each institution's OWN submissions.json (like the issuer one above)
//     lists that institution's OWN 13F-HR filings by accession number, but
//     you'd have to already know which of the ~5,000+ 13F filers to check,
//     and then still fetch and parse that filer's information-table XML
//     (which is CUSIP-keyed, not ticker-keyed, and can be tens of thousands
//     of lines for a large manager) to see if it mentions this ticker at
//     all — there is no reverse index from CUSIP/ticker back to filers.
//   - EDGAR full-text search (efts.sec.gov) indexes filing TEXT, not
//     structured XML table cells, so it cannot reliably answer "who holds
//     ticker X" either.
// Every third-party product that answers "13F by ticker" (multiple were
// found in research) is a paid or scraped aggregation of the bulk dataset,
// not a free SEC endpoint. So: this file intentionally ships ONLY (1) Form
// 4 insider activity. The route built on top of this file (see
// app/api/models/insider/route.ts) reports the 13F gap explicitly in its
// response rather than silently omitting it or faking a "no data" row that
// looks like an attempted-but-empty pull.
//
// SEC's fair-access requirements (verified 2026-09-13 via
// https://www.sec.gov/os/accessing-edgar-data — no API key exists, this is
// the entire requirement):
//   - A descriptive User-Agent header identifying the application and a
//     real contact, e.g. SEC's own example "Sample Company Name
//     AdminContact@<sample company domain>.com".
//   - A courtesy rate limit of 10 requests/second.
// This file does not hardcode a real person's contact (a personal email
// baked into source code and sent to a third-party server on every request
// is worse practice than the placeholder below, and this codebase should
// not ship one member's personal address as the desk's standing operational
// contact) — set SEC_EDGAR_CONTACT in the environment to the desk's real
// operator contact before relying on this in production; see
// .env.local.example.
export const SEC_USER_AGENT =
  process.env.SEC_EDGAR_CONTACT ||
  'WhiteWaterCapitalInsiderBot/1.0 (+https://whitewater-management.vercel.app; ' +
    'set SEC_EDGAR_CONTACT to a real operator contact per ' +
    'https://www.sec.gov/os/accessing-edgar-data)';

function secHeaders(accept) {
  return { 'User-Agent': SEC_USER_AGENT, Accept: accept || 'application/json' };
}

// ═══════════════════════════════════════════════════════════════════════════
// (1) Ticker -> CIK resolution
// ═══════════════════════════════════════════════════════════════════════════

const TICKER_DIRECTORY_URL = 'https://www.sec.gov/files/company_tickers.json';

// Pure parse, no network — kept separate from the fetch below so it can be
// hand-tested against a real (or realistic) payload without hitting the
// network. See scripts/verify-edgar-insider.mjs.
export function parseTickerDirectory(json) {
  const map = new Map();
  for (const row of Object.values(json || {})) {
    if (!row || !row.ticker || row.cik_str == null) continue;
    const cikNumeric = Number(row.cik_str);
    if (!Number.isFinite(cikNumeric)) continue;
    map.set(String(row.ticker).trim().toUpperCase(), {
      cikNumeric,
      cik: String(cikNumeric).padStart(10, '0'),
      name: row.title || null,
    });
  }
  return map;
}

// SEC regenerates company_tickers.json roughly daily; caching it in module
// scope (best-effort across warm Vercel invocations, same caveat as
// indicators/route.js's module-level cache) avoids re-downloading an
// ~800KB file on every distinct ticker lookup.
let tickerDirCache = { map: null, fetchedAt: 0 };
const TICKER_DIRECTORY_TTL_MS = 24 * 60 * 60 * 1000;

async function getTickerDirectory() {
  const now = Date.now();
  if (tickerDirCache.map && now - tickerDirCache.fetchedAt < TICKER_DIRECTORY_TTL_MS) {
    return tickerDirCache.map;
  }
  const resp = await fetch(TICKER_DIRECTORY_URL, { headers: secHeaders(), signal: AbortSignal.timeout(15000) });
  if (!resp.ok) throw new Error(`SEC ticker directory error ${resp.status}`);
  const json = await resp.json();
  const map = parseTickerDirectory(json);
  tickerDirCache = { map, fetchedAt: now };
  return map;
}

// Resolves an arbitrary ticker to its real SEC CIK, or null when SEC's own
// directory has no entry for it (a genuinely different answer from "SEC was
// unreachable", which this throws for instead — see fetchInsiderTransactions
// for how the two are kept distinguishable at the route boundary).
export async function resolveCik(ticker) {
  const t = String(ticker || '').trim().toUpperCase();
  if (!t) return null;
  const dir = await getTickerDirectory();
  return dir.get(t) || null;
}

// ═══════════════════════════════════════════════════════════════════════════
// (2) Recent Form 4 filings for a resolved CIK
// ═══════════════════════════════════════════════════════════════════════════

const FORM4_TYPES = new Set(['4', '4/A']);

async function fetchSubmissions(cikPadded) {
  const resp = await fetch(`https://data.sec.gov/submissions/CIK${cikPadded}.json`, {
    headers: secHeaders(),
    signal: AbortSignal.timeout(15000),
  });
  if (!resp.ok) throw new Error(`SEC submissions API error ${resp.status} for CIK${cikPadded}`);
  return resp.json();
}

// Pure parse, no network. submissions.json's filings.recent is a set of
// parallel arrays (same index = same filing) — this walks them once and
// keeps only Form 4 / 4-A entries at or after sinceDateISO.
//
// Honesty note on completeness: SEC's "recent" block holds roughly the
// most-recent ~1,000 filings of ANY type for that filer before rolling into
// numbered filings.files shards this function does not fetch. For a single
// ticker's Form 4s over a 90-day window that would require an implausibly
// high filing pace (>11 filings/day of every type, sustained) to actually
// truncate — but it is checked and reported (`truncated`) rather than
// silently assumed impossible, per this file's own no-fabrication rule.
export function pickForm4Filings(submissionsJson, { sinceDateISO } = {}) {
  const recent = submissionsJson?.filings?.recent;
  const forms = recent?.form;
  if (!Array.isArray(forms) || forms.length === 0) return { filings: [], truncated: false };

  const filings = [];
  for (let i = 0; i < forms.length; i++) {
    if (!FORM4_TYPES.has(forms[i])) continue;
    const filingDate = recent.filingDate?.[i] ?? null;
    if (sinceDateISO && filingDate && filingDate < sinceDateISO) continue;
    filings.push({
      accessionNumber: recent.accessionNumber?.[i],
      filingDate,
      reportDate: recent.reportDate?.[i] ?? null,
      primaryDocument: recent.primaryDocument?.[i] ?? null,
      isAmendment: forms[i] === '4/A',
    });
  }

  const oldestDate = recent.filingDate?.[forms.length - 1];
  const truncated = Boolean(
    sinceDateISO && oldestDate && oldestDate > sinceDateISO && forms.length >= 900,
  );
  return { filings, truncated };
}

function filingDirectoryUrl(cikNumeric, accessionNumber) {
  return `https://www.sec.gov/Archives/edgar/data/${cikNumeric}/${accessionNumber.replace(/-/g, '')}/`;
}

function filingDocUrl(cikNumeric, accessionNumber, primaryDocument) {
  return `${filingDirectoryUrl(cikNumeric, accessionNumber)}${primaryDocument}`;
}

// ═══════════════════════════════════════════════════════════════════════════
// (3) A real (not regex-hunting) XML parser for SEC's ownership-document
// (Form 3/4/5) schema, and the mapping from a parsed document to plain
// transaction records.
// ═══════════════════════════════════════════════════════════════════════════

function decodeXmlEntities(s) {
  return s
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(Number(d)))
    .replace(/&amp;/g, '&');
}

// Parses a full XML document into a plain nested-object tree: an element
// with child elements becomes an object keyed by child tag name (repeated
// sibling tags collapse into an array, same convention most XML->JSON
// converters use); a leaf element (no child elements) becomes a decoded,
// trimmed string. This is a complete parser for the shapes SEC's ownership
// schema actually uses — nesting, repeated siblings, leaf text, self-closing
// tags, comments, CDATA, the XML prolog — not a partial one hiding gaps. It
// does NOT support attributes carrying data (the ownership schema keeps all
// real data in element text, never attributes) or XML namespaces (the
// ownership schema doesn't use them either); an input that needed either
// would need a different parser, not a silently-wrong pass here.
export function parseXml(xmlText) {
  const src = String(xmlText)
    .replace(/<\?[\s\S]*?\?>/g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, (_, c) => c);

  const n = src.length;
  let i = 0;

  function parseElement() {
    if (src[i] !== '<') throw new Error(`parseXml: expected '<' at offset ${i}`);
    i++;
    const tagMatch = /^[^\s/>]+/.exec(src.slice(i));
    if (!tagMatch) throw new Error(`parseXml: malformed tag at offset ${i}`);
    const tag = tagMatch[0];
    i += tag.length;
    // Skip any attributes — real data in this schema never lives in one.
    while (i < n && src[i] !== '>' && src[i] !== '/') i++;
    if (src[i] === '/') {
      i += 2; // consume "/>"
      return { tag, value: '' };
    }
    i++; // consume '>'

    const children = {};
    let hasChildren = false;
    const textParts = [];

    while (i < n) {
      if (src.startsWith('</', i)) {
        i += 2;
        const closeEnd = src.indexOf('>', i);
        i = closeEnd + 1;
        break;
      }
      if (src[i] === '<') {
        hasChildren = true;
        const child = parseElement();
        if (!(child.tag in children)) {
          children[child.tag] = child.value;
        } else if (Array.isArray(children[child.tag])) {
          children[child.tag].push(child.value);
        } else {
          children[child.tag] = [children[child.tag], child.value];
        }
      } else {
        const start = i;
        while (i < n && src[i] !== '<') i++;
        textParts.push(src.slice(start, i));
      }
    }

    return hasChildren
      ? { tag, value: children }
      : { tag, value: decodeXmlEntities(textParts.join('')).trim() };
  }

  while (i < n && /\s/.test(src[i])) i++;
  if (i >= n) throw new Error('parseXml: empty document');
  const root = parseElement();
  return { [root.tag]: root.value };
}

// Walk a dotted path through a parsed-XML object tree, returning a string
// only for an actual leaf (never coerces an object/array into a string).
function leaf(obj, path) {
  let cur = obj;
  for (const key of path.split('.')) {
    if (cur == null) return null;
    cur = cur[key];
  }
  return typeof cur === 'string' ? cur : null;
}

// Most transaction fields in this schema wrap their real value in a
// <value> child (with an optional sibling <footnoteId>); a few (codes,
// booleans, names, CIKs) are plain leaf text. Try the wrapped shape first,
// fall back to the plain shape — correct either way.
function field(obj, name) {
  return leaf(obj, `${name}.value`) ?? leaf(obj, name);
}

function numOrNull(s) {
  if (s == null || s === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function toArray(x) {
  return x == null ? [] : Array.isArray(x) ? x : [x];
}

function truthyFlag(v) {
  return v === '1' || v === 'true' || v === '1.0';
}

function buildInsiders(doc) {
  const owners = toArray(doc.reportingOwner);
  const people = owners.map((o) => {
    const id = o.reportingOwnerId || {};
    const rel = o.reportingOwnerRelationship || {};
    const roles = [];
    if (truthyFlag(field(rel, 'isDirector'))) roles.push('Director');
    if (truthyFlag(field(rel, 'isTenPercentOwner'))) roles.push('10% owner');
    if (truthyFlag(field(rel, 'isOfficer'))) roles.push(field(rel, 'officerTitle') || 'Officer');
    if (truthyFlag(field(rel, 'isOther'))) roles.push(field(rel, 'otherText') || 'Other insider');
    return {
      name: field(id, 'rptOwnerName'),
      cik: field(id, 'rptOwnerCik'),
      roles: roles.length ? roles : ['Reporting person'],
    };
  });
  return {
    label: people.map((p) => p.name).filter(Boolean).join(' & ') || null,
    primaryCik: people[0]?.cik ?? null,
    roles: people.length ? Array.from(new Set(people.flatMap((p) => p.roles))) : [],
  };
}

// Human-readable label for a transaction code — SEC's own documented code
// list (Form 4 instructions, Table I/II column 3). Anything not in this
// list is shown as "Code <X> (unclassified)" rather than guessed at.
export const TRANSACTION_CODE_LABELS = {
  P: 'Open-market purchase',
  S: 'Open-market sale',
  A: 'Grant/award (compensation)',
  D: 'Disposition to issuer',
  F: 'Tax-withholding shares',
  M: 'Option exercise',
  G: 'Gift',
  C: 'Conversion of derivative',
  X: 'In-the-money option exercise',
  W: 'Acquisition/disposition by will or law',
  I: 'Discretionary transaction',
  J: 'Other (footnoted)',
  K: 'Equity swap',
  U: 'Tender of shares',
  Z: 'Voting trust deposit/withdrawal',
};

function mapTransactions(doc, tableName, txName, derivative, insiders, issuerMeta, filingMeta) {
  return toArray(doc[tableName]?.[txName]).map((t) => {
    const coding = t.transactionCoding || {};
    const amounts = t.transactionAmounts || {};
    const post = t.postTransactionAmounts || {};
    const ownership = t.ownershipNature || {};
    const code = leaf(coding, 'transactionCode');
    return {
      insiderName: insiders.label,
      insiderCik: insiders.primaryCik,
      insiderRoles: insiders.roles,
      securityTitle: field(t, 'securityTitle'),
      transactionDate: field(t, 'transactionDate'),
      formType: leaf(coding, 'transactionFormType'),
      transactionCode: code,
      transactionCodeLabel: TRANSACTION_CODE_LABELS[code] || (code ? `Code ${code} (unclassified)` : 'Unclassified'),
      shares: numOrNull(field(amounts, 'transactionShares')),
      pricePerShare: numOrNull(field(amounts, 'transactionPricePerShare')),
      acquiredDisposedCode: field(amounts, 'transactionAcquiredDisposedCode'),
      sharesOwnedAfter: numOrNull(field(post, 'sharesOwnedFollowingTransaction')),
      ownershipType: field(ownership, 'directOrIndirectOwnership'),
      derivative,
      issuerCik: issuerMeta.cik,
      issuerName: issuerMeta.name,
      issuerTicker: issuerMeta.ticker,
      filingDate: filingMeta.filingDate,
      reportDate: filingMeta.reportDate,
      accessionNumber: filingMeta.accessionNumber,
      isAmendment: Boolean(filingMeta.isAmendment),
      sourceUrl: filingMeta.sourceUrl,
    };
  });
}

// Pure parse, no network — the core of what makes this file's insider data
// traceable to a real source: every returned transaction carries the exact
// filing (accessionNumber + sourceUrl) it came from. See
// scripts/verify-edgar-insider.mjs for a hand-built realistic Form 4 XML
// (matching the live-verified schema in this file's header comment) run
// through this exact function.
export function parseForm4Xml(xmlText, filingMeta) {
  const doc = parseXml(xmlText)?.ownershipDocument;
  if (!doc) return [];

  const issuer = doc.issuer || {};
  const issuerMeta = {
    cik: field(issuer, 'issuerCik'),
    name: field(issuer, 'issuerName'),
    ticker: field(issuer, 'issuerTradingSymbol'),
  };
  const insiders = buildInsiders(doc);

  return [
    ...mapTransactions(doc, 'nonDerivativeTable', 'nonDerivativeTransaction', false, insiders, issuerMeta, filingMeta),
    ...mapTransactions(doc, 'derivativeTable', 'derivativeTransaction', true, insiders, issuerMeta, filingMeta),
  ];
}

// ═══════════════════════════════════════════════════════════════════════════
// Summarization — net insider buy/sell direction over the trailing window.
// ═══════════════════════════════════════════════════════════════════════════

// Only open-market purchases (P) and sales (S) count toward the directional
// score. Grants/awards (A), tax-withholding dispositions (F), option
// exercises (M), gifts (G) and the other administrative/compensation codes
// are real transactions and stay in the raw `transactions` list the panel
// shows, correctly labeled — but they are not a discretionary "putting
// capital behind a view" decision, and folding them into the score would
// dilute a real directional signal with routine compensation noise. This
// matches how insider-sentiment readings generally scope themselves (open-
// market Table I transactions only).
const SIGNAL_CODES = new Set(['P', 'S']);

// Confidence saturates at this many signal (P/S) transactions in the
// window. Chosen so 2 trades (plausibly one executive's own 10b5-1 plan
// tranches — not independent evidence) reads as low confidence (0.2), while
// 10+ signal transactions — plausibly several different insiders acting
// independently — reads as fully confident this isn't one person's
// idiosyncratic plan driving the whole number.
const CONFIDENCE_SATURATION_COUNT = 10;

// Pure, no network. `score` is null (not 0) when there is nothing to base
// one on — see this file's header and fetchInsiderTransactions for why "no
// signal transactions" must never collapse into a fabricated neutral score.
export function summarizeInsiderActivity(transactions, windowDays) {
  const signal = transactions.filter(
    (t) => !t.derivative && SIGNAL_CODES.has(t.transactionCode) && t.shares != null && t.pricePerShare != null,
  );

  if (signal.length === 0) {
    return {
      windowDays,
      signalTransactionCount: 0,
      buyCount: 0,
      sellCount: 0,
      buyDollars: 0,
      sellDollars: 0,
      netDirection: 0,
      score: null,
      confidence: 0,
      distinctInsiders: 0,
    };
  }

  let buyDollars = 0;
  let sellDollars = 0;
  let buyCount = 0;
  let sellCount = 0;
  const insiderCiks = new Set();
  for (const t of signal) {
    const dollars = t.shares * t.pricePerShare;
    if (t.transactionCode === 'P') {
      buyDollars += dollars;
      buyCount++;
    } else {
      sellDollars += dollars;
      sellCount++;
    }
    if (t.insiderCik) insiderCiks.add(t.insiderCik);
  }
  const gross = buyDollars + sellDollars;
  const netDirection = gross > 0 ? (buyDollars - sellDollars) / gross : 0; // -1..+1
  const score = Math.max(-100, Math.min(100, netDirection * 100));
  const confidence = Math.max(0, Math.min(1, signal.length / CONFIDENCE_SATURATION_COUNT));

  return {
    windowDays,
    signalTransactionCount: signal.length,
    buyCount,
    sellCount,
    buyDollars,
    sellDollars,
    netDirection,
    score,
    confidence,
    distinctInsiders: insiderCiks.size,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// Orchestrator — the one function the route calls.
// ═══════════════════════════════════════════════════════════════════════════

const DEFAULT_WINDOW_DAYS = 90; // long enough to catch a quarter's cadence of
// Form 4 filings (most insiders file only when they actually transact, so a
// shorter window risks reading "no filings this week" as "no activity" when
// it's really "nothing happened to file"), short enough that the read is
// still about current sentiment, not stale history.

// Real HTTP fetches per request are capped here — a name with a genuinely
// unusual volume of insider filings still gets a fast, bounded response
// (and stays comfortably under SEC's 10 req/sec courtesy limit even before
// this route's own cache dedupes repeat requests for the same ticker).
// `filingsCappedAt` on the result says plainly when this triggered.
const MAX_FILINGS_TO_FETCH = 40;

// Three-way-distinguishable result. `status`:
//   'not_found'   — SEC's own ticker directory has no CIK for this ticker.
//   'unreachable' — a real network/HTTP failure talking to SEC (transient or
//                   this environment's own egress, not a statement about
//                   the ticker at all).
//   'ok'          — SEC was reached and the ticker resolved; `transactions`
//                   may still be an empty array, which means "SEC has no
//                   Form 4 filings for this issuer in the window" — a real,
//                   different, and equally valid answer from the two above.
export async function fetchInsiderTransactions(ticker, { windowDays = DEFAULT_WINDOW_DAYS } = {}) {
  const t = String(ticker || '').trim().toUpperCase();
  if (!t) return { status: 'not_found', ticker: t, message: 'No ticker provided.' };

  let identity;
  try {
    identity = await resolveCik(t);
  } catch (err) {
    return { status: 'unreachable', ticker: t, message: `Couldn't reach SEC's ticker directory: ${err.message}` };
  }
  if (!identity) {
    return {
      status: 'not_found',
      ticker: t,
      message: `No SEC CIK found for "${t}" in SEC's own ticker directory — either not a US-listed equity SEC tracks, or the ticker is wrong.`,
    };
  }

  const sinceDateISO = new Date(Date.now() - windowDays * 86400000).toISOString().slice(0, 10);

  let submissions;
  try {
    submissions = await fetchSubmissions(identity.cik);
  } catch (err) {
    return {
      status: 'unreachable',
      ticker: t,
      cik: identity.cik,
      companyName: identity.name,
      message: `Couldn't reach SEC's submissions API: ${err.message}`,
    };
  }

  const { filings, truncated } = pickForm4Filings(submissions, { sinceDateISO });
  const capped = filings.slice(0, MAX_FILINGS_TO_FETCH);

  const settled = await Promise.allSettled(
    capped.map(async (f) => {
      if (!f.accessionNumber || !f.primaryDocument) return [];
      const url = filingDocUrl(identity.cikNumeric, f.accessionNumber, f.primaryDocument);
      const resp = await fetch(url, { headers: secHeaders('application/xml'), signal: AbortSignal.timeout(15000) });
      if (!resp.ok) throw new Error(`${resp.status} fetching ${f.accessionNumber}`);
      const xml = await resp.text();
      return parseForm4Xml(xml, {
        accessionNumber: f.accessionNumber,
        filingDate: f.filingDate,
        reportDate: f.reportDate,
        isAmendment: f.isAmendment,
        sourceUrl: filingDirectoryUrl(identity.cikNumeric, f.accessionNumber),
      });
    }),
  );

  const transactions = [];
  let filingFetchFailures = 0;
  settled.forEach((r) => {
    if (r.status === 'fulfilled') transactions.push(...r.value);
    else filingFetchFailures++;
  });
  transactions.sort((a, b) => String(b.transactionDate || '').localeCompare(String(a.transactionDate || '')));

  return {
    status: 'ok',
    ticker: t,
    cik: identity.cik,
    companyName: identity.name,
    windowDays,
    sinceDate: sinceDateISO,
    filingsFound: filings.length,
    filingsFetched: capped.length,
    filingFetchFailures,
    filingsCappedAt: filings.length > MAX_FILINGS_TO_FETCH ? MAX_FILINGS_TO_FETCH : null,
    windowMayBeIncomplete: truncated,
    transactions,
    summary: summarizeInsiderActivity(transactions, windowDays),
  };
}
