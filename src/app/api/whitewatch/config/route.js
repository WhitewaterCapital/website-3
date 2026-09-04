import { NextResponse } from 'next/server';

// Tells the frontend which optional upgrades are wired up, purely for the
// Dashboard tab's status cards — never exposes the key values themselves.
export async function GET() {
  return NextResponse.json({
    mapbox: Boolean(process.env.MAPBOX_TOKEN),
    newsapi: Boolean(process.env.NEWSAPI_KEY),
    acled: Boolean(process.env.ACLED_API_KEY),
    anthropic: Boolean(process.env.ANTHROPIC_API_KEY),
    xTwitter: Boolean(process.env.X_BEARER_TOKEN),
    firms: Boolean(process.env.FIRMS_MAP_KEY),
    fredCommodities: Boolean(process.env.FRED_API_KEY),
  });
}
