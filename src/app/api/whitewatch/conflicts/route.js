import { NextResponse } from 'next/server';
import conflicts from '../../../../lib/whitewatch-data/conflicts.json';

// Curated conflict-zone + strategic-chokepoint dataset. Swap this for a live
// ACLED pull once ACLED_API_KEY / ACLED_EMAIL are set — the response shape
// below ({ id, name, region, lat, lng, threat, status, summary, actors, tags })
// is the contract WarMapClient expects, so a real data source just needs to
// map into it.
export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const threat = searchParams.get('threat');
  const region = searchParams.get('region');

  let data = conflicts;
  if (threat) data = data.filter((c) => c.threat === threat);
  if (region) data = data.filter((c) => c.region.toLowerCase().includes(region.toLowerCase()));

  return NextResponse.json({
    items: data,
    count: data.length,
    source: process.env.ACLED_API_KEY ? 'acled' : 'curated',
  });
}
