import { NextResponse } from 'next/server';
import conflicts from '../../../../lib/whitewatch-data/conflicts.json';

// Daily rollup, computed live from the curated dataset — no key required.
// Gets richer once ANTHROPIC_API_KEY is set (see the predictions route for
// that pattern) by summarizing the day's feed instead of just counting.
export async function GET() {
  const byThreat = { critical: 0, high: 0, medium: 0, low: 0 };
  conflicts.forEach((c) => {
    byThreat[c.threat] = (byThreat[c.threat] || 0) + 1;
  });

  return NextResponse.json({
    generatedAt: new Date().toISOString(),
    headline: `${byThreat.critical} critical and ${byThreat.high} high-threat zones under active monitoring.`,
    threatBreakdown: byThreat,
    watchlist: conflicts
      .filter((c) => c.threat === 'critical' || c.threat === 'high')
      .map((c) => ({ id: c.id, name: c.name, threat: c.threat, status: c.status, summary: c.summary })),
  });
}
