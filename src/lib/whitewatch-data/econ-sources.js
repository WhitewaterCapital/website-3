import 'server-only';

// Shared fetch helpers for the three free, keyless data sources used across
// Whitewatch's country-level economic/humanitarian data:
//   - World Bank Open Data API — energy/electricity/water/etc.
//   - IMF DataMapper API — GDP growth + inflation.
//   - UNHCR Refugee Statistics API — forced displacement.
//
// Originally lived inline in app/api/whitewatch/indicators/route.js (see
// that file's history for the "verified live" notes on each source); pulled
// out here so /api/whitewatch/country-data can fetch the *same* indicators
// for an arbitrary single country (e.g. one clicked on the map that isn't
// on indicators/route.js's curated DEFAULT_COUNTRIES list) without
// reimplementing the World Bank/IMF/UNHCR request shapes twice.

export const WB_INDICATORS = {
  energyUsePerCapitaKgOilEq: 'EG.USE.PCAP.KG.OE', // kg oil equivalent per capita
  electricAccessPct: 'EG.ELC.ACCS.ZS', // % of population with electricity access
  freshwaterWithdrawalBillionM3: 'ER.H2O.FWTL.K3', // total annual freshwater withdrawal
  freshwaterWithdrawalPctResources: 'ER.H2O.FWTL.ZS', // % of internal renewable resources
  gdpUsd: 'NY.GDP.MKTP.CD', // GDP, current US$ — broad general-purpose indicator so
  // even a country with none of the above still has something to show.
  populationTotal: 'SP.POP.TOTL',
};

// IMF DataMapper indicator codes — exact WEO series IDs, verified live
// during development of indicators/route.js.
export const IMF_INDICATORS = {
  gdpGrowthPct: 'NGDP_RPCH', // real GDP growth, annual %
  inflationPct: 'PCPIPCH', // inflation, average consumer prices, annual %
};

export async function fetchWbIndicator(code, countries) {
  const url = `https://api.worldbank.org/v2/country/${countries.join(';')}/indicator/${code}?format=json&per_page=500&mrnev=1`;
  const resp = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
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
// country -> {year: value}) and filters to the tracked list here instead.
export async function fetchImfIndicator(code, countries) {
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

export async function fetchUnhcr(countries) {
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
