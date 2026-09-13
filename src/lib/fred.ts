import "server-only";

// ═══════════════════════════════════════════════════════════════════════════
// Shared FRED (Federal Reserve Economic Data) fetch helper.
//
// Factored out of distresse.ts's own local `fetchFredLatest` (see
// PLATFORM_REBUILD_PLAN.md priority #5's own note recommending exactly this)
// so Distresse's "Macro regime fit" dimension and Macro Tracker's real-regime
// fallback both call one real, cached implementation instead of two
// duplicated copies of the same fetch+cache logic.
//
// Free, keyless-once-FRED_API_KEY-is-set: https://fred.stlouisfed.org/docs/api/api_key.html
// Both functions below return null (never throw) when the key is unset or
// the request fails — callers are expected to abstain honestly, never
// substitute a fabricated number for a null return.
// ═══════════════════════════════════════════════════════════════════════════

const FRED_CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6h — matches the commodities route's own FRED TTL

export type FredObservation = { value: number; date: string };

type CacheEntry = { data: FredObservation[]; fetchedAt: number };
const fredCache = new Map<string, CacheEntry>();

async function fetchFredObservations(seriesId: string, limit: number): Promise<FredObservation[]> {
  const apiKey = process.env.FRED_API_KEY;
  if (!apiKey) return [];

  const cacheKey = `${seriesId}:${limit}`;
  const cached = fredCache.get(cacheKey);
  const now = Date.now();
  if (cached && now - cached.fetchedAt < FRED_CACHE_TTL_MS) return cached.data;

  try {
    const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${seriesId}&api_key=${apiKey}&file_type=json&sort_order=desc&limit=${limit}`;
    const resp = await fetch(url, { signal: AbortSignal.timeout(12000) });
    if (!resp.ok) return [];
    const json = await resp.json();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const obs = ((json.observations || []) as any[]).filter((o) => o.value !== "."); // FRED uses "." for missing days
    const data = obs.map((o) => ({ value: Number(o.value), date: o.date as string }));
    fredCache.set(cacheKey, { data, fetchedAt: now });
    return data;
  } catch {
    return [];
  }
}

// The single most recent real observation for a series, or null if the key
// is unset, the series has no recent data, or the request failed.
export async function fetchFredLatest(seriesId: string): Promise<FredObservation | null> {
  const obs = await fetchFredObservations(seriesId, 5); // 5, not 1 — skips "." gaps around weekends/holidays
  return obs[0] ?? null;
}

// Up to `count` most recent real observations, most-recent-first — for
// trend reads (e.g. "are initial claims rising or falling") that a single
// latest value can't answer. Empty array under the same conditions as above.
export async function fetchFredSeries(seriesId: string, count = 8): Promise<FredObservation[]> {
  return fetchFredObservations(seriesId, count);
}
