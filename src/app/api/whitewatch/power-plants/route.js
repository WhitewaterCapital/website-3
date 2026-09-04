import { NextResponse } from 'next/server';

// Live pull + parse of the Global Power Plant Database (World Resources
// Institute, CC BY 4.0). Verified working 2026-08-30 — real CSV, real
// columns (country, country_long, name, capacity_mw, latitude, longitude,
// primary_fuel, commissioning_year, owner, ...).
// https://github.com/wri/global-power-plant-database
export const runtime = 'nodejs';

const CSV_URL =
  'https://raw.githubusercontent.com/wri/global-power-plant-database/master/output_database/global_power_plant_database.csv';

// Curated emerging-market scope (ISO3 codes) — edit freely to widen/narrow.
const EMERGING_MARKETS = new Set([
  'IND', 'BRA', 'IDN', 'ZAF', 'VNM', 'NGA', 'TUR', 'EGY', 'MEX', 'ARG', 'PAK', 'BGD',
  'PHL', 'THA', 'KEN', 'ETH', 'COL', 'PER', 'MAR', 'DZA', 'CHN', 'SAU', 'ARE', 'QAT',
  'MYS', 'CHL', 'POL', 'ROU',
]);

let cache = { items: null, fetchedAt: 0 };
const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24h — plant capacity barely changes day to day

// Minimal quote-aware CSV line splitter — GPPD has commas inside quoted
// owner/source fields, so a plain split(',') would misalign columns.
function splitCsvLine(line) {
  const out = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === ',' && !inQuotes) {
      out.push(cur);
      cur = '';
    } else {
      cur += ch;
    }
  }
  out.push(cur);
  return out;
}

async function fetchPlants() {
  const resp = await fetch(CSV_URL);
  if (!resp.ok) throw new Error(`GPPD fetch error ${resp.status}`);
  const text = await resp.text();
  const lines = text.split('\n').filter(Boolean);
  const header = splitCsvLine(lines[0]);
  const idx = (name) => header.indexOf(name);
  const iCountry = idx('country');
  const iCountryLong = idx('country_long');
  const iName = idx('name');
  const iCapacity = idx('capacity_mw');
  const iLat = idx('latitude');
  const iLon = idx('longitude');
  const iFuel = idx('primary_fuel');
  const iYear = idx('commissioning_year');
  const iOwner = idx('owner');

  const items = [];
  for (let i = 1; i < lines.length; i++) {
    const row = splitCsvLine(lines[i]);
    const country = row[iCountry];
    if (!EMERGING_MARKETS.has(country)) continue;
    const capacity = parseFloat(row[iCapacity]);
    if (!capacity) continue;
    items.push({
      country,
      countryName: row[iCountryLong],
      name: row[iName],
      capacityMw: capacity,
      lat: parseFloat(row[iLat]) || null,
      lng: parseFloat(row[iLon]) || null,
      fuel: row[iFuel] || 'Unknown',
      commissioningYear: row[iYear] ? Math.round(Number(row[iYear])) : null,
      owner: row[iOwner] || null,
    });
  }
  items.sort((a, b) => b.capacityMw - a.capacityMw);
  return items;
}

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const country = searchParams.get('country');
  const fuel = searchParams.get('fuel');
  const limit = Number(searchParams.get('limit') || 60);

  try {
    const now = Date.now();
    if (!cache.items || now - cache.fetchedAt > CACHE_TTL_MS) {
      cache = { items: await fetchPlants(), fetchedAt: now };
    }

    let items = cache.items;
    if (country) items = items.filter((p) => p.country === country.toUpperCase());
    if (fuel) items = items.filter((p) => (p.fuel || '').toLowerCase() === fuel.toLowerCase());

    return NextResponse.json({
      source: 'Global Power Plant Database, World Resources Institute (CC BY 4.0)',
      sourceUrl: 'https://github.com/wri/global-power-plant-database',
      scope: 'Filtered to a curated list of emerging-market countries — edit EMERGING_MARKETS in this file to change scope.',
      fetchedAt: cache.fetchedAt,
      count: items.length,
      items: items.slice(0, limit),
    });
  } catch (err) {
    console.error('Power plants fetch failed:', err.message);
    return NextResponse.json({ error: 'Failed to fetch power plant data', items: [] }, { status: 500 });
  }
}
