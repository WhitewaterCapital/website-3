import { NextResponse } from 'next/server';
import { WB_INDICATORS, IMF_INDICATORS, fetchWbIndicator, fetchImfIndicator, fetchUnhcr } from '../../../../lib/whitewatch-data/econ-sources';
import { resolveIso3 } from '../../../../lib/whitewatch-data/country-codes';

// Per-country data for the War Map's click panel — ANY of the ~180
// countries the map's choropleth renders, not just the ~20 curated
// conflict zones. This is what makes "click the Netherlands and see it
// moved a lot of gold out of the US" possible: /api/whitewatch/indicators
// already pulls real World Bank + IMF + UNHCR data, but only for its own
// curated DEFAULT_COUNTRIES list; this route reuses that exact same
// fetch logic (see lib/whitewatch-data/econ-sources.js) for a single
// arbitrary ISO3 requested on demand, plus a small set of recent GDELT
// headlines about that country (same free/keyless GDELT DOC 2.0 API the
// Intel Feed already uses — see app/api/whitewatch/news/route.js).
//
// Every source that comes back empty for a given country says so plainly
// (an explicit `available: false` + `note`) instead of omitting the
// section or inventing a number — matching the "unavailable" language
// used elsewhere in this codebase (see components/panels/DigestPanel.tsx).
export const runtime = 'nodejs';

// A handful of country names GDELT's free-text search would otherwise
// collide with common-word or celebrity-name matches — bias the query
// toward country-scale news for these without needing a paid NER service.
// Directional, not authoritative, same as the keyword heuristics in
// app/api/whitewatch/news/route.js.
const AMBIGUOUS_NAME_HINTS = {
  Georgia: 'Tbilisi OR government OR president',
  Jordan: 'Amman OR kingdom OR government',
  Chad: "N'Djamena OR government OR president",
  Turkey: 'Ankara OR Erdogan OR government',
  Niger: 'Niamey OR government OR junta',
  Guinea: 'Conakry OR government',
};

function parseGdeltDate(seendate) {
  if (!seendate || seendate.length < 15) return null;
  const iso = `${seendate.slice(0, 4)}-${seendate.slice(4, 6)}-${seendate.slice(6, 8)}T${seendate.slice(9, 11)}:${seendate.slice(11, 13)}:${seendate.slice(13, 15)}Z`;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

// Same GDELT DOC 2.0 endpoint/shape as app/api/whitewatch/news/route.js's
// fetchGdelt(), scoped to one country's name instead of a global
// conflict-keyword query.
async function fetchGdeltForCountry(countryName) {
  const hint = AMBIGUOUS_NAME_HINTS[countryName];
  const query = hint ? `"${countryName}" (${hint}) sourcelang:eng` : `"${countryName}" sourcelang:eng`;
  const url = `https://api.gdeltproject.org/api/v2/doc/doc?query=${encodeURIComponent(query)}&mode=artlist&format=json&maxrecords=8&sort=datedesc&timespan=3d`;
  const resp = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0 (WhitewatchIntelBot/1.0)' },
    signal: AbortSignal.timeout(12000),
  });
  if (!resp.ok) throw new Error(`GDELT API error ${resp.status}`);
  const json = await resp.json();
  const articles = json?.articles || [];
  return articles
    .map((a) => ({
      title: a.title,
      link: a.url,
      source: a.domain || 'web',
      sourceCountry: a.sourcecountry || null,
      publishedAt: parseGdeltDate(a.seendate),
    }))
    .filter((item) => item.title && item.link);
}

// Two caches with different lifetimes, matching how fast each underlying
// source actually changes: World Bank/IMF/UNHCR figures are annual and
// barely move (12h TTL, same constant indicators/route.js uses); GDELT
// headlines are near-real-time (15min TTL, close to the Intel Feed's 5min).
// Both are best-effort, module-level, per-lambda-instance caches — same
// caveat as every other cache in this codebase (see news/route.js).
const econCache = new Map(); // iso3 -> { data, fetchedAt }
const ECON_CACHE_TTL_MS = 12 * 60 * 60 * 1000;
const newsCache = new Map(); // iso3 -> { items, fetchedAt }
const NEWS_CACHE_TTL_MS = 15 * 60 * 1000;

async function getEconAndDisplacement(iso3) {
  const cached = econCache.get(iso3);
  const now = Date.now();
  if (cached && now - cached.fetchedAt < ECON_CACHE_TTL_MS) return cached.data;

  const results = await Promise.allSettled([
    fetchWbIndicator(WB_INDICATORS.gdpUsd, [iso3]),
    fetchWbIndicator(WB_INDICATORS.populationTotal, [iso3]),
    fetchWbIndicator(WB_INDICATORS.energyUsePerCapitaKgOilEq, [iso3]),
    fetchWbIndicator(WB_INDICATORS.electricAccessPct, [iso3]),
    fetchWbIndicator(WB_INDICATORS.freshwaterWithdrawalBillionM3, [iso3]),
    fetchImfIndicator(IMF_INDICATORS.gdpGrowthPct, [iso3]),
    fetchImfIndicator(IMF_INDICATORS.inflationPct, [iso3]),
    fetchUnhcr([iso3]),
  ]);
  const [gdpUsd, population, energy, electric, water, gdpGrowth, inflation, displacement] = results.map((r) =>
    r.status === 'fulfilled' ? r.value : {}
  );
  results.forEach((r, i) => {
    if (r.status === 'rejected') console.error(`country-data source ${i} failed for ${iso3}:`, r.reason?.message);
  });

  const countryName =
    gdpUsd[iso3]?.country || population[iso3]?.country || energy[iso3]?.country || electric[iso3]?.country || null;

  const econ = {
    gdpUsd: gdpUsd[iso3]?.value ?? null,
    gdpUsdYear: gdpUsd[iso3]?.date ?? null,
    population: population[iso3]?.value ?? null,
    populationYear: population[iso3]?.date ?? null,
    energyUsePerCapitaKgOilEq: energy[iso3]?.value ?? null,
    energyUsePerCapitaYear: energy[iso3]?.date ?? null,
    electricAccessPct: electric[iso3]?.value ?? null,
    electricAccessYear: electric[iso3]?.date ?? null,
    freshwaterWithdrawalBillionM3: water[iso3]?.value ?? null,
    freshwaterWithdrawalYear: water[iso3]?.date ?? null,
    gdpGrowthPct: gdpGrowth[iso3]?.value ?? null,
    gdpGrowthYear: gdpGrowth[iso3]?.year ?? null,
    inflationPct: inflation[iso3]?.value ?? null,
    inflationYear: inflation[iso3]?.year ?? null,
  };
  const econAvailable = Object.entries(econ).some(([k, v]) => !k.endsWith('Year') && v !== null);

  const disp = displacement[iso3] || null;
  const displacementPayload = disp
    ? { available: true, refugeesOrigin: disp.refugees ?? null, idps: disp.idps ?? null, asylumSeekers: disp.asylumSeekers ?? null, year: disp.year ?? null, note: null }
    : { available: false, refugeesOrigin: null, idps: null, asylumSeekers: null, year: null, note: 'No UNHCR displacement data available for this country.' };

  const data = {
    countryName,
    econ: { available: econAvailable, note: econAvailable ? null : 'No World Bank or IMF data available for this country.', ...econ },
    displacement: displacementPayload,
  };
  econCache.set(iso3, { data, fetchedAt: now });
  return data;
}

async function getNews(countryName) {
  const cacheKey = countryName;
  const cached = newsCache.get(cacheKey);
  const now = Date.now();
  if (cached && now - cached.fetchedAt < NEWS_CACHE_TTL_MS) return cached.items;

  let items = [];
  try {
    items = await fetchGdeltForCountry(countryName);
  } catch (err) {
    console.error(`country-data GDELT fetch failed for ${countryName}:`, err.message);
  }
  newsCache.set(cacheKey, { items, fetchedAt: now });
  return items;
}

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const nameParam = searchParams.get('name');
  const iso3Param = searchParams.get('iso3');

  const iso3 = iso3Param ? iso3Param.trim().toUpperCase() : resolveIso3(nameParam);
  const displayNameFallback = nameParam || iso3Param || 'Unknown';

  if (!iso3) {
    return NextResponse.json({
      resolved: false,
      query: { name: nameParam, iso3: iso3Param },
      country: displayNameFallback,
      message: `No ISO3 country-code mapping found for "${displayNameFallback}" — country-level economic/news data is unavailable for this polygon.`,
    });
  }

  try {
    const [econAndDisplacement, newsItems] = await Promise.all([
      getEconAndDisplacement(iso3),
      getNews(displayNameFallback === 'Unknown' ? iso3 : displayNameFallback),
    ]);

    return NextResponse.json({
      resolved: true,
      iso3,
      country: displayNameFallback !== 'Unknown' ? displayNameFallback : econAndDisplacement.countryName || iso3,
      generatedAt: new Date().toISOString(),
      econ: econAndDisplacement.econ,
      displacement: econAndDisplacement.displacement,
      news: {
        available: newsItems.length > 0,
        items: newsItems,
        note: newsItems.length > 0 ? null : 'No recent GDELT headlines matched this country in the last 3 days.',
      },
      source: 'World Bank Open Data + IMF DataMapper + UNHCR Refugee Statistics + GDELT DOC 2.0 — all public, no key required',
    });
  } catch (err) {
    console.error(`country-data fetch failed for ${iso3}:`, err.message);
    return NextResponse.json(
      { resolved: true, iso3, country: displayNameFallback, error: 'Failed to fetch country data', econ: { available: false }, displacement: { available: false }, news: { available: false, items: [] } },
      { status: 500 }
    );
  }
}
