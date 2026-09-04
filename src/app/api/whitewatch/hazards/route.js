import { NextResponse } from 'next/server';

// Two independent live point-feed layers for the map:
//   - NASA FIRMS (active fire/thermal-anomaly detections) — free, but
//     requires a personal MAP_KEY from a short signup form. STUB (live:false)
//     until FIRMS_MAP_KEY is set — same honest-placeholder pattern as
//     /api/whitewatch/x-feed. Verified real via firms.modaps.eosdis.nasa.gov
//     during development; not re-fetched live here since no key is available
//     to test with in this environment.
//   - USGS Earthquake GeoJSON feed — fully free, keyless, always live.
//     Verified live: earthquake.usgs.gov/earthquakes/feed/v1.0/summary/
//     updates every minute straight from USGS's own real-time feed.
export const runtime = 'nodejs';

const FIRMS_SOURCE = 'VIIRS_SNPP_NRT'; // ~375m resolution, near-real-time, good balance of coverage vs. noise
const FIRMS_DAY_RANGE = 1;

// USGS magnitude/period thresholds: 4.5_day keeps the layer to a legible
// number of points (roughly a few dozen at a time worldwide) while still
// surfacing anything a hedge fund desk would plausibly care about.
const USGS_FEED = 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson';

let cache = { data: null, fetchedAt: 0 };
const CACHE_TTL_MS = 10 * 60 * 1000; // 10 min — fires update every ~3h at the source, quakes every minute, this is a reasonable middle ground

// FIRMS returns CSV, not JSON: latitude,longitude,brightness,scan,track,
// acq_date,acq_time,satellite,confidence,version,bright_t31,frp,daynight
function parseFirmsCsv(text) {
  const lines = text.trim().split('\n');
  if (lines.length < 2) return [];
  const header = lines[0].split(',').map((h) => h.trim());
  const idx = (name) => header.indexOf(name);
  const iLat = idx('latitude');
  const iLon = idx('longitude');
  const iBright = idx('bright_ti4') !== -1 ? idx('bright_ti4') : idx('brightness');
  const iConf = idx('confidence');
  const iDate = idx('acq_date');
  const iTime = idx('acq_time');
  const iFrp = idx('frp');
  const iSat = idx('satellite');
  if (iLat === -1 || iLon === -1) return [];

  return lines.slice(1).map((line, i) => {
    const cols = line.split(',');
    const lat = Number(cols[iLat]);
    const lng = Number(cols[iLon]);
    return {
      id: `firms-${i}-${cols[iDate]}-${cols[iTime]}`,
      lat,
      lng,
      brightness: iBright !== -1 ? Number(cols[iBright]) : null,
      confidence: iConf !== -1 ? cols[iConf] : null,
      acqDate: iDate !== -1 ? cols[iDate] : null,
      acqTime: iTime !== -1 ? cols[iTime] : null,
      frp: iFrp !== -1 ? Number(cols[iFrp]) : null,
      satellite: iSat !== -1 ? cols[iSat] : null,
    };
  }).filter((f) => Number.isFinite(f.lat) && Number.isFinite(f.lng));
}

async function fetchFires() {
  const mapKey = process.env.FIRMS_MAP_KEY;
  if (!mapKey) {
    return {
      live: false,
      note:
        'FIRMS_MAP_KEY not set — this layer is fully wired but inactive. Get a free MAP_KEY (instant, no approval wait) at https://firms.modaps.eosdis.nasa.gov/api/area/, then add FIRMS_MAP_KEY in Vercel.',
      source: 'NASA FIRMS',
      count: 0,
      items: [],
    };
  }
  const url = `https://firms.modaps.eosdis.nasa.gov/api/area/csv/${mapKey}/${FIRMS_SOURCE}/world/${FIRMS_DAY_RANGE}`;
  const resp = await fetch(url, { signal: AbortSignal.timeout(15000) });
  if (!resp.ok) throw new Error(`FIRMS API error ${resp.status}`);
  const text = await resp.text();
  const items = parseFirmsCsv(text);
  return { live: true, source: `NASA FIRMS (${FIRMS_SOURCE}, last ${FIRMS_DAY_RANGE}d)`, count: items.length, items };
}

async function fetchQuakes() {
  const resp = await fetch(USGS_FEED, {
    headers: { 'User-Agent': 'Mozilla/5.0 (WhitewatchIntelBot/1.0)' },
    signal: AbortSignal.timeout(15000),
  });
  if (!resp.ok) throw new Error(`USGS earthquake API error ${resp.status}`);
  const json = await resp.json();
  const features = json?.features || [];
  const items = features.map((f) => {
    const [lng, lat, depthKm] = f.geometry?.coordinates || [];
    const p = f.properties || {};
    return {
      id: f.id,
      lat,
      lng,
      depthKm,
      mag: p.mag,
      magType: p.magType,
      place: p.place,
      time: p.time ? new Date(p.time).toISOString() : null,
      alert: p.alert || null,
      tsunami: Boolean(p.tsunami),
      felt: p.felt ?? null,
      url: p.url || null,
    };
  }).filter((q) => Number.isFinite(q.lat) && Number.isFinite(q.lng));
  return { live: true, source: 'USGS Earthquake Hazards Program (M4.5+, past day)', count: items.length, items };
}

export async function GET() {
  const now = Date.now();
  if (cache.data && now - cache.fetchedAt < CACHE_TTL_MS) {
    return NextResponse.json(cache.data);
  }

  const [firesResult, quakesResult] = await Promise.allSettled([fetchFires(), fetchQuakes()]);

  const fires =
    firesResult.status === 'fulfilled'
      ? firesResult.value
      : { live: false, note: `Fetch failed: ${firesResult.reason?.message || 'unknown error'}`, source: 'NASA FIRMS', count: 0, items: [] };
  const quakes =
    quakesResult.status === 'fulfilled'
      ? quakesResult.value
      : { live: false, note: `Fetch failed: ${quakesResult.reason?.message || 'unknown error'}`, source: 'USGS Earthquake Hazards Program', count: 0, items: [] };

  if (firesResult.status === 'rejected') console.error('FIRMS fetch failed:', firesResult.reason?.message);
  if (quakesResult.status === 'rejected') console.error('USGS quakes fetch failed:', quakesResult.reason?.message);

  const payload = { fires, quakes, generatedAt: new Date().toISOString() };
  cache = { data: payload, fetchedAt: now };
  return NextResponse.json(payload);
}
