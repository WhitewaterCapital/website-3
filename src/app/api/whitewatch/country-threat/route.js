import { NextResponse } from 'next/server';
import raw from '../../../../lib/whitewatch-data/country-threat.json';

// Every country in the world gets a tier via this map, keyed by the exact
// name string world-atlas/Natural Earth uses (properties.name) — see
// WarMapClient's COUNTRY_TO_ZONE and the fill-color match expression.
// Anything not listed here defaults to "stable" client-side.
export async function GET() {
  const { _comment, ...countryThreat } = raw;
  return NextResponse.json(countryThreat);
}
