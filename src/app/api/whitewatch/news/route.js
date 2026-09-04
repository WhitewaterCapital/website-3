import { NextResponse } from 'next/server';
import Parser from 'rss-parser';

// Force the Node.js runtime (rss-parser needs Node APIs, not the Edge runtime).
export const runtime = 'nodejs';

const parser = new Parser({
  timeout: 8000,
  headers: { 'User-Agent': 'Mozilla/5.0 (WhitewatchIntelBot/1.0)' },
  // Most of these feeds carry an article thumbnail in one of these tags
  // rather than plain <enclosure> — pull them in as raw fields so
  // extractImage() below has something to work with.
  customFields: {
    item: [
      ['media:content', 'mediaContent', { keepArray: true }],
      ['media:thumbnail', 'mediaThumbnail'],
    ],
  },
});

// Not every feed guarantees an image — this tries the common places in
// order and returns null rather than guessing, so the UI can fall back to
// a plain text card instead of a broken <img>.
function extractImage(item) {
  if (item.enclosure?.url) return item.enclosure.url;
  if (item.mediaThumbnail?.$?.url) return item.mediaThumbnail.$.url;
  if (Array.isArray(item.mediaContent) && item.mediaContent[0]?.$?.url) return item.mediaContent[0].$.url;
  const html = item['content:encoded'] || item.content || '';
  const match = /<img[^>]+src="([^"]+)"/i.exec(html);
  return match ? match[1] : null;
}

// Rough keyword-based region tagging (same directional-not-authoritative
// caveat as classifyThreat below) so the region filter chips actually mean
// something instead of every item being "Global".
const REGION_KEYWORDS = {
  'Middle East': ['israel', 'gaza', 'palestin', 'iran', 'lebanon', 'syria', 'yemen', 'iraq', 'saudi', 'hormuz', 'red sea'],
  Europe: ['ukraine', 'russia', 'nato', 'poland', 'european union', 'moscow', 'kyiv', 'kremlin'],
  'East Asia': ['china', 'taiwan', 'korea', 'japan', 'beijing', 'pyongyang'],
  'South Asia': ['india', 'pakistan', 'afghanistan', 'bangladesh', 'nepal'],
  Africa: ['sudan', 'congo', 'mali', 'niger', 'somalia', 'nigeria', 'ethiopia', 'sahel'],
  Americas: ['united states', 'u.s.', 'mexico', 'brazil', 'venezuela', 'colombia'],
  'Southeast Asia': ['myanmar', 'philippines', 'vietnam', 'indonesia', 'south china sea'],
};

function classifyRegion(text) {
  const lower = text.toLowerCase();
  for (const [region, kws] of Object.entries(REGION_KEYWORDS)) {
    if (kws.some((kw) => lower.includes(kw))) return region;
  }
  return 'Global';
}

// Public, freely-syndicated RSS feeds — no API key required. Each entry
// aggregates headline + summary + link back to the source; we never
// republish full article bodies.
const FEEDS = [
  { source: 'BBC World', region: 'Global', url: 'http://feeds.bbci.co.uk/news/world/rss.xml' },
  { source: 'Al Jazeera', region: 'Global', url: 'https://www.aljazeera.com/xml/rss/all.xml' },
  { source: 'NYT World', region: 'Global', url: 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml' },
  { source: 'The Guardian World', region: 'Global', url: 'https://www.theguardian.com/world/rss' },
  { source: 'DW World', region: 'Global', url: 'https://rss.dw.com/rdf/rss-en-world' },
  { source: 'Reuters World (Google News)', region: 'Global', url: 'https://news.google.com/rss/search?q=site:reuters.com+world&hl=en-US&gl=US&ceid=US:en' },
  // Verified live 2026-08-30: valid RSS 2.0, resolves real UN News items.
  { source: 'UN News', region: 'Global', url: 'https://news.un.org/feed/subscribe/en/news/all/rss.xml' },
];

// Rough heuristic for "report"-style items (economic/data releases, IMF/World
// Bank/UN output) vs regular spot news — same keyword-matching approach as
// classifyThreat below, so treat it as directional, not authoritative.
const REPORT_KEYWORDS = [
  'report', 'imf', 'world bank', 'gdp', 'inflation', 'outlook', 'forecast',
  'survey', 'data show', 'study finds', 'united nations report', 'index',
];

function classifyCategory(text) {
  const lower = text.toLowerCase();
  return REPORT_KEYWORDS.some((kw) => lower.includes(kw)) ? 'report' : 'news';
}

// Rough keyword-based threat/region tagging so items can be filtered without
// a paid classifier. Swap for a real model via ANTHROPIC_API_KEY — see
// /api/whitewatch/predictions for that pattern.
const THREAT_KEYWORDS = {
  critical: ['killed', 'strike', 'invasion', 'airstrike', 'missile attack', 'dead', 'offensive', 'nuclear'],
  high: ['attack', 'clash', 'troops', 'military', 'conflict', 'war', 'ceasefire', 'sanctions'],
  medium: ['tension', 'warns', 'deploy', 'border', 'talks', 'protest'],
};

function classifyThreat(text) {
  const lower = text.toLowerCase();
  for (const level of ['critical', 'high', 'medium']) {
    if (THREAT_KEYWORDS[level].some((kw) => lower.includes(kw))) return level;
  }
  return 'low';
}

// GDELT DOC 2.0 API — global, multi-language news monitoring, updated
// continuously (the underlying dataset refreshes every 15 minutes).
// Verified live 2026-08-31 against api.gdeltproject.org/api/v2/doc/doc —
// free, keyless, no signup. GDELT's own courtesy rate limit is "one
// request every 5 seconds"; this route only calls it once per CACHE_TTL_MS
// (5 min) refresh, well under that. Query is scoped to the same
// conflict/geopolitics focus as the curated RSS feeds above.
const GDELT_QUERY = '(war OR conflict OR military OR sanctions OR coup OR ceasefire OR strike OR invasion OR airstrike OR unrest) sourcelang:eng';
const GDELT_URL = `https://api.gdeltproject.org/api/v2/doc/doc?query=${encodeURIComponent(GDELT_QUERY)}&mode=artlist&format=json&maxrecords=75&sort=datedesc&timespan=1d`;

// GDELT's seendate looks like "20260831T120000Z" — convert to a real ISO
// string so it sorts/parses the same way as the RSS feeds' publishedAt.
function parseGdeltDate(seendate) {
  if (!seendate || seendate.length < 15) return null;
  const iso = `${seendate.slice(0, 4)}-${seendate.slice(4, 6)}-${seendate.slice(6, 8)}T${seendate.slice(9, 11)}:${seendate.slice(11, 13)}:${seendate.slice(13, 15)}Z`;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

async function fetchGdelt() {
  const resp = await fetch(GDELT_URL, {
    headers: { 'User-Agent': 'Mozilla/5.0 (WhitewatchIntelBot/1.0)' },
    signal: AbortSignal.timeout(12000),
  });
  if (!resp.ok) throw new Error(`GDELT API error ${resp.status}`);
  const json = await resp.json();
  const articles = json?.articles || [];
  return articles
    .map((a) => {
      const text = `${a.title || ''}`;
      return {
        id: a.url,
        title: a.title,
        summary: a.domain ? `${a.domain}${a.sourcecountry ? ` — ${a.sourcecountry}` : ''}` : '',
        link: a.url,
        image: a.socialimage || null,
        source: `GDELT (${a.domain || 'web'})`,
        region: classifyRegion(text),
        publishedAt: parseGdeltDate(a.seendate),
        threat: classifyThreat(text),
        category: classifyCategory(text),
      };
    })
    .filter((item) => item.title && item.link);
}

// Module-level cache: best-effort only. On Vercel this persists across warm
// invocations of the same lambda instance but is NOT shared/guaranteed
// across instances or cold starts — that's fine here, it just means an
// occasional extra RSS fetch, never stale-forever or incorrect data.
let cache = { items: [], fetchedAt: 0 };
const CACHE_TTL_MS = 5 * 60 * 1000;

async function fetchAllFeeds() {
  const results = await Promise.allSettled(
    FEEDS.map(async (feed) => {
      const parsed = await parser.parseURL(feed.url);
      return (parsed.items || []).slice(0, 15).map((item) => {
        const text = `${item.title || ''} ${item.contentSnippet || ''}`;
        return {
          id: item.guid || item.link,
          title: item.title,
          summary: (item.contentSnippet || '').slice(0, 240),
          link: item.link,
          image: extractImage(item),
          source: feed.source,
          region: classifyRegion(text),
          publishedAt: item.isoDate || item.pubDate || null,
          threat: classifyThreat(text),
          category: classifyCategory(text),
        };
      });
    })
  );

  results.push(await fetchGdelt().then(
    (value) => ({ status: 'fulfilled', value }),
    (reason) => ({ status: 'rejected', reason })
  ));
  if (results[results.length - 1].status === 'rejected') {
    console.error('GDELT fetch failed:', results[results.length - 1].reason?.message);
  }

  const items = results
    .filter((r) => r.status === 'fulfilled')
    .flatMap((r) => r.value)
    .filter((item) => item.title && item.link)
    .sort((a, b) => new Date(b.publishedAt || 0) - new Date(a.publishedAt || 0));

  const seen = new Set();
  const deduped = [];
  for (const item of items) {
    const key = item.title.trim().toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(item);
  }
  return deduped;
}

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  try {
    const now = Date.now();
    if (now - cache.fetchedAt > CACHE_TTL_MS || cache.items.length === 0) {
      const items = await fetchAllFeeds();
      if (items.length > 0) cache = { items, fetchedAt: now };
    }

    let items = cache.items;
    const region = searchParams.get('region');
    const threat = searchParams.get('threat');
    const category = searchParams.get('category'); // 'report' | 'news'
    const q = searchParams.get('q');
    const limit = searchParams.get('limit');

    if (region) items = items.filter((i) => i.region.toLowerCase() === region.toLowerCase());
    if (threat) items = items.filter((i) => i.threat === threat);
    if (category) items = items.filter((i) => i.category === category);
    if (q) {
      const needle = q.toLowerCase();
      items = items.filter((i) => i.title.toLowerCase().includes(needle) || i.summary.toLowerCase().includes(needle));
    }
    if (limit) items = items.slice(0, Number(limit));

    return NextResponse.json({ items, fetchedAt: cache.fetchedAt, count: items.length, stale: cache.items.length === 0 });
  } catch (err) {
    console.error('News feed error:', err.message);
    return NextResponse.json({ error: 'Failed to fetch news feed', items: [] }, { status: 500 });
  }
}
