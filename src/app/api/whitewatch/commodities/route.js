import { NextResponse } from 'next/server';

// FRED (Federal Reserve Bank of St. Louis) API — daily commodity spot/
// benchmark prices. STUB (live:false) until FRED_API_KEY is set — same
// honest-placeholder pattern as /api/whitewatch/x-feed and the FIRMS layer
// in /api/whitewatch/hazards.
//
// Series verified live on fred.stlouisfed.org 2026-08-31 (the public series
// pages, which don't require a key to view):
//   - DCOILWTICO: "Crude Oil Prices: WTI" — $/barrel, live value confirmed.
//   - DCOILBRENTEU: "Crude Oil Prices: Brent - Europe" — $/barrel, $88.24
//     as of 2026-08-25 confirmed live.
//   - DHHNGSP: "Henry Hub Natural Gas Spot Price" — $/MMBtu, $2.70 as of
//     2026-08-25 confirmed live.
// A gold series (GOLDAMGBD228NLBM) was considered but FRED discontinued
// its LBMA-sourced gold/silver series in 2022 (ICE Benchmark Administration
// pulled the data) — confirmed via FRED's own 2022 removal notice, so gold
// is intentionally left out rather than shipped with a dead series ID.
export const runtime = 'nodejs';

const SERIES = [
  { id: 'DCOILWTICO', label: 'WTI Crude', unit: '$/barrel' },
  { id: 'DCOILBRENTEU', label: 'Brent Crude', unit: '$/barrel' },
  { id: 'DHHNGSP', label: 'Henry Hub Natural Gas', unit: '$/MMBtu' },
];

let cache = { data: null, fetchedAt: 0 };
const CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6h — these series update once/day at most

async function fetchSeries(apiKey, series) {
  const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${series.id}&api_key=${apiKey}&file_type=json&sort_order=desc&limit=5`;
  const resp = await fetch(url, { signal: AbortSignal.timeout(12000) });
  if (!resp.ok) throw new Error(`FRED API error ${resp.status} for ${series.id}`);
  const json = await resp.json();
  const observations = (json.observations || []).filter((o) => o.value !== '.'); // FRED uses "." for missing days
  const latest = observations[0];
  return {
    id: series.id,
    label: series.label,
    unit: series.unit,
    value: latest ? Number(latest.value) : null,
    date: latest ? latest.date : null,
  };
}

export async function GET() {
  const apiKey = process.env.FRED_API_KEY;
  if (!apiKey) {
    return NextResponse.json({
      live: false,
      note:
        'FRED_API_KEY not set — this route is fully wired but inactive. Get a free API key (instant, no cost) at https://fredaccount.stlouisfed.org/apikeys, then add FRED_API_KEY in Vercel.',
      items: [],
    });
  }

  const now = Date.now();
  if (cache.data && now - cache.fetchedAt < CACHE_TTL_MS) {
    return NextResponse.json(cache.data);
  }

  try {
    const results = await Promise.allSettled(SERIES.map((s) => fetchSeries(apiKey, s)));
    const items = results.filter((r) => r.status === 'fulfilled').map((r) => r.value);
    results.forEach((r, i) => {
      if (r.status === 'rejected') console.error(`FRED series ${SERIES[i].id} failed:`, r.reason?.message);
    });

    const payload = { live: true, generatedAt: new Date().toISOString(), items };
    cache = { data: payload, fetchedAt: now };
    return NextResponse.json(payload);
  } catch (err) {
    console.error('Commodities fetch failed:', err.message);
    return NextResponse.json({ error: 'Failed to fetch commodities', live: false, items: [] }, { status: 500 });
  }
}
