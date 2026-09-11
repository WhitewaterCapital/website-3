import { NextResponse } from 'next/server';
import { WB_INDICATORS, IMF_INDICATORS, fetchWbIndicator, fetchImfIndicator, fetchUnhcr } from '../../../../lib/whitewatch-data/econ-sources';

// Live pull from THREE free, keyless sources, merged by ISO3 country code:
//   - World Bank Open Data API — energy/electricity/water (unchanged, see below)
//   - IMF DataMapper API — GDP growth + inflation. Verified live 2026-08-31
//     by querying https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH
//     directly: real JSON, real ISO3 keys, no auth required at all — not
//     even a free-signup key, unlike most of the other new sources added
//     this round (FIRMS, FRED).
//   - UNHCR Refugee Statistics API — forced displacement. Verified live
//     2026-08-31 against https://api.unhcr.org/population/v1/population/
//     with a real query (coo=SDN) — returned real 2023 figures (1.5M
//     refugees, 9M+ IDPs from Sudan), keyless.
//
// The actual fetch* functions and indicator code tables now live in
// lib/whitewatch-data/econ-sources.js so /api/whitewatch/country-data can
// reuse the exact same World Bank/IMF/UNHCR request logic for a single
// arbitrary country (e.g. one clicked on the map that isn't in this route's
// curated DEFAULT_COUNTRIES list below) instead of reimplementing it.
export const runtime = 'nodejs';

// Same country set as country-threat.json plus a broader emerging-market
// spread, so this tab has coverage beyond just the conflict-zone list.
const DEFAULT_COUNTRIES = [
  'UKR', 'ISR', 'PSE', 'SDN', 'YEM', 'IRN', 'LBN', 'SYR', 'PRK', 'MLI', 'NER', 'BFA',
  'COD', 'MMR', 'SOM', 'AFG', 'SSD', 'RUS', 'TWN',
  'IND', 'BRA', 'IDN', 'ZAF', 'VNM', 'NGA', 'TUR', 'EGY', 'MEX', 'ARG', 'PAK', 'BGD',
  'PHL', 'THA', 'KEN', 'ETH', 'COL', 'PER', 'MAR', 'DZA', 'CHN', 'SAU', 'ARE', 'QAT',
];

let cache = { data: null, key: null, fetchedAt: 0 };
const CACHE_TTL_MS = 12 * 60 * 60 * 1000; // 12h — these indicators move slowly

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const countriesParam = searchParams.get('countries');
  const countries = countriesParam
    ? countriesParam.split(',').map((c) => c.trim().toUpperCase()).filter(Boolean)
    : DEFAULT_COUNTRIES;

  const cacheKey = countries.join(',');
  const now = Date.now();
  if (cache.data && cache.key === cacheKey && now - cache.fetchedAt < CACHE_TTL_MS) {
    return NextResponse.json(cache.data);
  }

  try {
    const results = await Promise.allSettled([
      fetchWbIndicator(WB_INDICATORS.energyUsePerCapitaKgOilEq, countries),
      fetchWbIndicator(WB_INDICATORS.electricAccessPct, countries),
      fetchWbIndicator(WB_INDICATORS.freshwaterWithdrawalBillionM3, countries),
      fetchWbIndicator(WB_INDICATORS.freshwaterWithdrawalPctResources, countries),
      fetchImfIndicator(IMF_INDICATORS.gdpGrowthPct, countries),
      fetchImfIndicator(IMF_INDICATORS.inflationPct, countries),
      fetchUnhcr(countries),
    ]);
    const [energy, electric, waterTotal, waterPct, gdpGrowth, inflation, displacement] = results.map((r) =>
      r.status === 'fulfilled' ? r.value : {}
    );
    results.forEach((r, i) => {
      if (r.status === 'rejected') console.error(`Indicator source ${i} failed:`, r.reason?.message);
    });

    const items = countries
      .map((iso3) => ({
        iso3,
        country:
          energy[iso3]?.country || electric[iso3]?.country || waterTotal[iso3]?.country || waterPct[iso3]?.country || iso3,
        energyUsePerCapitaKgOilEq: energy[iso3]?.value ?? null,
        energyUsePerCapitaYear: energy[iso3]?.date ?? null,
        electricAccessPct: electric[iso3]?.value ?? null,
        electricAccessYear: electric[iso3]?.date ?? null,
        freshwaterWithdrawalBillionM3: waterTotal[iso3]?.value ?? null,
        freshwaterWithdrawalYear: waterTotal[iso3]?.date ?? null,
        freshwaterWithdrawalPctResources: waterPct[iso3]?.value ?? null,
        gdpGrowthPct: gdpGrowth[iso3]?.value ?? null,
        gdpGrowthYear: gdpGrowth[iso3]?.year ?? null,
        inflationPct: inflation[iso3]?.value ?? null,
        inflationYear: inflation[iso3]?.year ?? null,
        refugeesOrigin: displacement[iso3]?.refugees ?? null,
        idps: displacement[iso3]?.idps ?? null,
        displacementYear: displacement[iso3]?.year ?? null,
      }))
      .filter(
        (row) =>
          row.energyUsePerCapitaKgOilEq !== null ||
          row.electricAccessPct !== null ||
          row.freshwaterWithdrawalBillionM3 !== null ||
          row.gdpGrowthPct !== null ||
          row.inflationPct !== null ||
          row.refugeesOrigin !== null
      );

    const payload = {
      source: 'World Bank Open Data + IMF DataMapper + UNHCR Refugee Statistics — all public, no key required',
      note:
        "Energy-use-per-capita is IEA-sourced and often several years behind (many countries cap out around 2014-15); electricity access updates more frequently. IMF figures beyond the current year are IMF's own WEO projections, not actuals — check *Year fields. UNHCR displacement figures lag by roughly a year and count people displaced FROM that country (origin), not hosted there.",
      generatedAt: new Date().toISOString(),
      items,
    };

    cache = { data: payload, key: cacheKey, fetchedAt: now };
    return NextResponse.json(payload);
  } catch (err) {
    console.error('Indicators fetch failed:', err.message);
    return NextResponse.json({ error: 'Failed to fetch indicators', items: [] }, { status: 500 });
  }
}
