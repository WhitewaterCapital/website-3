import { NextResponse } from 'next/server';

// X (formerly Twitter) API v2 recent-search. STUB until X_BEARER_TOKEN is
// set — same honest-placeholder pattern as /api/whitewatch/predictions.
//
// Note for setup: X's free API tier does not include search access as of
// this writing — you need a paid Basic tier (or higher) developer account
// at https://developer.x.com to get a bearer token that can call this
// endpoint. That's a real cost, not a formality; decide if it's worth it
// before wiring the key in.
export const runtime = 'nodejs';

const DEFAULT_QUERY = '(conflict OR ceasefire OR sanctions OR airstrike OR "troop movement") -is:retweet lang:en';

export async function GET(request) {
  const bearerToken = process.env.X_BEARER_TOKEN;
  const { searchParams } = new URL(request.url);
  const query = searchParams.get('q') || DEFAULT_QUERY;

  if (!bearerToken) {
    return NextResponse.json({
      live: false,
      note:
        'X_BEARER_TOKEN not set — this route is fully wired but inactive. Requires an X Developer account on the paid Basic tier or higher (the free tier has no search access). Get a bearer token at https://developer.x.com, then add X_BEARER_TOKEN in Vercel.',
      items: [],
    });
  }

  try {
    const url = `https://api.x.com/2/tweets/search/recent?query=${encodeURIComponent(
      query
    )}&max_results=20&tweet.fields=created_at,author_id,public_metrics&expansions=author_id&user.fields=username,name`;
    const resp = await fetch(url, { headers: { Authorization: `Bearer ${bearerToken}` } });
    if (!resp.ok) throw new Error(`X API error ${resp.status}`);
    const data = await resp.json();

    const users = Object.fromEntries((data.includes?.users || []).map((u) => [u.id, u]));
    const items = (data.data || []).map((t) => {
      const author = users[t.author_id];
      return {
        id: t.id,
        text: t.text,
        createdAt: t.created_at,
        author: author?.username ? `@${author.username}` : t.author_id,
        metrics: t.public_metrics || null,
        link: author?.username ? `https://x.com/${author.username}/status/${t.id}` : `https://x.com/i/status/${t.id}`,
      };
    });

    return NextResponse.json({ live: true, query, items });
  } catch (err) {
    console.error('X feed fetch failed:', err.message);
    return NextResponse.json({ error: 'Failed to fetch X feed', live: false, items: [] }, { status: 500 });
  }
}
