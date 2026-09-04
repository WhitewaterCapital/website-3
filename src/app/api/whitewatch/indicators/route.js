import { NextResponse } from 'next/server';

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
export const runtime = 'nodejs';

const WB_INDICATORS = {
  energyUsePerCapitaKgOilEq: 'EG.USE.PCAP.KG.OE', // kg oil equivalent per capita
  electricAccessPct: 'EG.ELC.ACCS.ZS', // % of population with electricity access
  freshwaterWithdrawalBillionM3: 'ER.H2O.FWTL.K3', // total annual freshwater withdrawal
  freshwaterWithdrawalPctResources: 'ER.H2O.FWTL.ZS', // % of internal renewable resources
};

// IMF DataMapper indicator codes — these are the exact WEO series IDs,
// verified live during development (see comment above).
const IMF_INDICATORS = {
  gdpGrowthPct: 'NGDP_RPCH', // real GDP growth, annual %
  inflationPct: 'PCPIPCH', // inflation, average consumer prices, annual %
};

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

async function fetchWbIndicator(code, countries) {
  const url = `https://api.worldbank.org/v2/country/${countries.join(';')}/indicator/${code}?format=json&per_page=500&mrnev=1`;
  const resp = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!resp.ok) throw new Error(`World Bank API error ${resp.status} for ${code}`);
  const json = await resp.json();
  const rows = Array.isArray(json) && Array.isArray(json[1]) ? json[1] : [];
  const byCountry = {};
  rows.forEach((row) => {
    if (row.value === null || row.value === undefined) return;
    const iso3 = row.countryiso3code || row.country?.id;
    if (!iso3) return;
    byCountry[iso3] = { value: row.value, date: row.date, country: row.country?.value };
  });
  return byCountry;
}

// DataMapper has no reliable multi-country path filter across its whole
// history of indicator codes, so this pulls the full global dataset per
// indicator (confirmed small enough to be fast — a JSON object of
// country -> {year: value}) and filters to our tracked list here instead.
async function fetchImfIndicator(code, countries) {
  const resp = await fetch(`https://www.imf.org/external/datamapper/api/v1/${code}`, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(15000),
  });
  if (!resp.ok) throw new Error(`IMF DataMapper API error ${resp.status} for ${code}`);
  const json = await resp.json();
  const values = json?.values?.[code] || {};
  const byCountry = {};
  const countrySet = new Set(countries);
  for (const [iso3, yearMap] of Object.entries(values)) {
    if (!countrySet.has(iso3)) continue;
    const years = Object.keys(yearMap).filter((y) => yearMap[y] !== null && yearMap[y] !== undefined);
    if (years.length === 0) continue;
    // Prefer the latest year that isn't an IMF forward-looking projection
    // beyond next year, so this reads as "latest known" not "latest guess".
    const currentYear = new Date().getFullYear();
    const usable = years.filter((y) => Number(y) <= currentYear + 1).sort();
    const year = usable[usable.length - 1] || years.sort()[years.length - 1];
    byCountry[iso3] = { value: yearMap[year], year };
  }
  return byCountry;
}

async function fetchUnhcr(countries) {
  const currentYear = new Date().getFullYear();
  const url = `https://api.unhcr.org/population/v1/population/?coo_all=true&cf_type=ISO&yearFrom=${currentYear - 4}&yearTo=${currentYear}&limit=2000`;
  const resp = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
  if (!resp.ok) throw new Error(`UNHCR API error ${resp.status}`);
  const json = await resp.json();
  const rows = json?.items || json?.data || [];
  const countrySet = new Set(countries);
  const byCountry = {};
  for (const row of rows) {
    const iso3 = row.coo_iso || row.coo;
    if (!iso3 || !countrySet.has(iso3)) continue;
    const existing = byCountry[iso3];
    if (existing && Number(existing.year) >= Number(row.year)) continue; // keep the most recent year per country
    byCountry[iso3] = {
      year: row.year,
      refugees: row.refugees ?? 0,
      idps: row.idps ?? 0,
      asylumSeekers: row.asylum_seekers ?? 0,
    };
  }
  return byCountry;
}

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
