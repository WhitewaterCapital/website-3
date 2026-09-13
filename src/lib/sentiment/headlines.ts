import "server-only";
import Parser from "rss-parser";
import type { Headline } from "./types";

// ---------------------------------------------------------------------------
// Per-ticker headline fetch — same free, keyless mechanism as
// src/app/api/whitewatch/news/route.js's "Reuters World (Google News)" feed
// entry: Google News' public RSS search endpoint, no API key, no signup.
// That route already relies on this exact host/path/query-param shape for
// one of its seven feeds; this module reuses it for an arbitrary
// ticker/company query instead of a fixed topic.
//
// NOT independently re-verified live from THIS sandbox: this environment has
// no outbound network access at all (see the constraints in this task and
// graph-engine/README.md's "Current status" section for the same caveat
// applied to that engine's live Tiingo path). The whitewatch news route's own
// comments only claim "verified live" for the feeds it explicitly tested
// (BBC, UN News) — this ticker-scoped query was built against the same
// documented Google News RSS shape, not separately confirmed working end to
// end. The first real confirmation is the first real request a deployed
// instance actually makes.
// ---------------------------------------------------------------------------

const parser = new Parser({
  timeout: 8000,
  headers: { "User-Agent": "Mozilla/5.0 (WhitewatchSentimentBot/1.0)" },
});

// How far back to search. Google News' `when:` search operator is an
// unofficial (undocumented by Google, but long-standing and widely relied
// upon — e.g. every "site:reuters.com when:7d" style query in common use)
// recency filter, not a formal API parameter — flagged here rather than
// presented as a guaranteed contract, same spirit as the news route's own
// "directional, not authoritative" caveats on its keyword classifiers.
const LOOKBACK = "when:14d";

// Cap on how many raw feed items we even ask rss-parser to hand back before
// dedupe/scoring — scoring costs one real HTTP call per headline (see
// finbert.ts), so this also bounds how many of those calls one ticker
// request can trigger.
const MAX_RAW_ITEMS = 40;

function buildQuery(ticker: string, companyName: string | null): string {
  // Quoting the ticker avoids Google News treating it as a generic word
  // (e.g. bare `T` or `META` are far too ambiguous unquoted). When a real
  // company name is available (from Incepta's SecurityAnalysis.name — see
  // route.ts), OR it into the query so a headline that names the company
  // but not the ticker symbol is still found.
  const parts = [`"${ticker}"`];
  if (companyName && companyName.trim()) parts.push(`"${companyName.trim()}"`);
  const namePart = parts.length > 1 ? `(${parts.join(" OR ")})` : parts[0];
  return `${namePart} ${LOOKBACK}`;
}

// Fetches real, deduped, dated, linked headlines for one ticker. Returns an
// empty array (never throws, never fabricates) on any failure — the caller
// (route.ts) is responsible for turning "zero headlines" into an honest
// abstain, not this function's job.
export async function fetchTickerHeadlines(
  ticker: string,
  companyName: string | null,
): Promise<Omit<Headline, "sentiment">[]> {
  const query = buildQuery(ticker, companyName);
  const url = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=en-US&gl=US&ceid=US:en`;

  let items: Parser.Item[];
  try {
    const parsed = await parser.parseURL(url);
    items = parsed.items ?? [];
  } catch (err) {
    console.error(`[sentiment] headline fetch failed for ${ticker}:`, (err as Error).message);
    return [];
  }

  const seen = new Set<string>();
  const out: Omit<Headline, "sentiment">[] = [];
  for (const item of items.slice(0, MAX_RAW_ITEMS)) {
    const title = item.title?.trim();
    const link = item.link?.trim();
    if (!title || !link) continue; // never publish a headline missing either — same rule as the whitewatch news route
    const key = title.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      id: item.guid || link,
      title,
      // Google News titles are conventionally "Headline text - Publisher";
      // split that off when present so `source` is real attribution, not a
      // guess. Falls back to the feed's own <source> field, then "Google
      // News" — never a fabricated publisher name.
      source: title.includes(" - ") ? title.split(" - ").pop()!.trim() : (item as { source?: string }).source || "Google News",
      link,
      publishedAt: item.isoDate || item.pubDate || null,
    });
  }
  return out;
}
