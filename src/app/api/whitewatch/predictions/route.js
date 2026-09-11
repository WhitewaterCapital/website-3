import { NextResponse } from 'next/server';
import conflicts from '../../../../lib/whitewatch-data/conflicts.json';

export const runtime = 'nodejs';

// STUB until ANTHROPIC_API_KEY is set — returns clearly labeled placeholder
// analysis so the UI is fully wired and demoable without a key.
//
// claude-sonnet-5 (not a dated snapshot) so this keeps working as the
// current generation rolls forward, rather than pinning to a model that
// will eventually be retired — this route only ever calls the API once a
// key is actually configured, so there's no reproducibility need pinning
// would buy here.
async function callClaude(prompt) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  const resp = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-sonnet-5',
      max_tokens: 500,
      messages: [{ role: 'user', content: prompt }],
    }),
  });
  if (!resp.ok) throw new Error(`Anthropic API error: ${resp.status}`);
  const data = await resp.json();
  return data.content?.[0]?.text || '';
}

// Best-effort parse of the model's JSON reply into the exact same
// { id, name, threat, outlook }[] shape the placeholder returns, so the
// UI renders the SAME card layout whether or not a key is configured —
// before this, the live path returned one raw text blob (a different,
// worse-looking shape) instead of matching the polished placeholder.
// Never throws: a reply that isn't parseable JSON falls back to the raw
// text rather than a crash, and is labeled as such downstream.
function parsePredictions(text, fallbackConflicts) {
  const stripped = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/i, '');
  try {
    const parsed = JSON.parse(stripped);
    if (Array.isArray(parsed) && parsed.every((p) => p && typeof p.outlook === 'string')) {
      return parsed.map((p, i) => ({
        id: p.id || fallbackConflicts[i]?.id || `pred-${i}`,
        name: p.name || fallbackConflicts[i]?.name || 'Unknown',
        threat: p.threat || fallbackConflicts[i]?.threat || 'medium',
        outlook: p.outlook,
      }));
    }
  } catch {
    // fall through to the raw-text fallback below
  }
  return null;
}

export async function GET() {
  const apiKey = process.env.ANTHROPIC_API_KEY;

  if (!apiKey) {
    return NextResponse.json({
      live: false,
      note: 'ANTHROPIC_API_KEY not set — showing placeholder analysis. Add the key in Vercel’s Environment Variables to enable live AI predictions.',
      items: conflicts.slice(0, 6).map((c) => ({
        id: c.id,
        name: c.name,
        threat: c.threat,
        outlook: `[placeholder] Trend analysis for ${c.name} will appear here once an AI key is configured.`,
      })),
    });
  }

  try {
    const target = conflicts.slice(0, 6);
    const prompt =
      'You are a geopolitical risk analyst. Given this JSON list of active conflict zones, write a one-sentence, ' +
      'non-alarmist forward-looking outlook (7-day horizon) for each, focused on trajectory ' +
      '(escalating/stable/de-escalating) and the key driver.\n\n' +
      'Respond with ONLY a JSON array (no prose, no markdown fences), one object per zone, each shaped exactly like: ' +
      '{"id": "<the zone\'s id from the input>", "name": "<the zone\'s name from the input>", ' +
      '"threat": "<the zone\'s threat from the input>", "outlook": "<your one-sentence outlook>"}\n\n' +
      JSON.stringify(target);
    const text = await callClaude(prompt);
    const items = parsePredictions(text, target);
    if (items) return NextResponse.json({ live: true, items });
    // Model didn't return parseable JSON — still real output, just not in
    // the structured shape, so say so rather than pretending it's the
    // placeholder's format.
    return NextResponse.json({ live: true, note: 'Live model reply — not in the expected structured format, shown as-is.', items: text });
  } catch (err) {
    console.error('Predictions error:', err.message);
    return NextResponse.json({ error: 'Prediction generation failed', live: false }, { status: 500 });
  }
}
