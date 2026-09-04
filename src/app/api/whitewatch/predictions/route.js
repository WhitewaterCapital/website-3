import { NextResponse } from 'next/server';
import conflicts from '../../../../lib/whitewatch-data/conflicts.json';

export const runtime = 'nodejs';

// STUB until ANTHROPIC_API_KEY is set — returns clearly labeled placeholder
// analysis so the UI is fully wired and demoable without a key.
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
      model: 'claude-sonnet-4-5-20250929',
      max_tokens: 400,
      messages: [{ role: 'user', content: prompt }],
    }),
  });
  if (!resp.ok) throw new Error(`Anthropic API error: ${resp.status}`);
  const data = await resp.json();
  return data.content?.[0]?.text || '';
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
    const target = conflicts.slice(0, 5);
    const prompt = `You are a geopolitical risk analyst. Given this JSON list of active conflict zones, write a one-sentence, non-alarmist forward-looking outlook (7-day horizon) for each, focused on trajectory (escalating/stable/de-escalating) and the key driver. Return concise plain text, one line per zone, prefixed with the zone name.\n\n${JSON.stringify(target)}`;
    const text = await callClaude(prompt);
    return NextResponse.json({ live: true, items: text });
  } catch (err) {
    console.error('Predictions error:', err.message);
    return NextResponse.json({ error: 'Prediction generation failed', live: false }, { status: 500 });
  }
}
