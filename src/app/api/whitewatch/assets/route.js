import { NextResponse } from 'next/server';

// Live, keyless, global asset layer — mines, ports, smelters, refineries and
// dams — pulled from THREE independent live sources and merged, so no
// single source's gaps become the layer's gaps:
//   1. Wikidata SPARQL query service — the primary source, richest fields
//      (operator, commodities) when present.
//   2. OpenStreetMap (Overpass API) — crowd-mapped points Wikidata hasn't
//      gotten a dedicated item for yet. Live, free, keyless.
//   3. USGS MRDS (mines only) — a legacy-but-real global mineral deposit
//      catalog via USGS's own OGC WFS service. Live, free, keyless — but
//      frozen since 2011, see the caveat on MRDS below.
//
// Verified live 2026-08-31 by querying each endpoint directly during
// development, not assumed from memory or documentation — see the
// per-source comments for exactly what was checked and how.
export const runtime = 'nodejs';

const USER_AGENT =
  'Mozilla/5.0 (compatible; WhitewatchAssetBot/1.0; +https://whitewater-management.vercel.app) desk-research-tool';

const ASSET_TYPES = {
  mine: { qid: 'Q820477', label: 'Mine' },
  port: { qid: 'Q44782', label: 'Port' },
  smelter: { qid: 'Q65515162', label: 'Smelter' },
  refinery: { qid: 'Q12353044', label: 'Refinery' },
  dam: { qid: 'Q12323', label: 'Dam' },
};

// Same scope as the Power Plants layer (curated emerging-market list, kept
// in sync with EMERGING_MARKETS in ../power-plants/route.js) plus the
// active conflict-zone countries from lib/whitewatch-data/country-threat.json.
// Widen it here any time — every source below (Wikidata, OSM, MRDS) is
// filtered against this same list, one way or another.
const ASSET_COUNTRIES = {
  // name -> [Wikidata QID, ISO 3166-1 alpha-2]
  India: ['Q668', 'IN'], Brazil: ['Q155', 'BR'], Indonesia: ['Q252', 'ID'], 'South Africa': ['Q258', 'ZA'],
  Vietnam: ['Q881', 'VN'], Nigeria: ['Q1033', 'NG'], Turkey: ['Q43', 'TR'], Egypt: ['Q79', 'EG'], Mexico: ['Q96', 'MX'],
  Argentina: ['Q414', 'AR'], Pakistan: ['Q843', 'PK'], Bangladesh: ['Q902', 'BD'], Philippines: ['Q928', 'PH'],
  Thailand: ['Q869', 'TH'], Kenya: ['Q114', 'KE'], Ethiopia: ['Q115', 'ET'], Colombia: ['Q739', 'CO'], Peru: ['Q419', 'PE'],
  Morocco: ['Q1028', 'MA'], Algeria: ['Q262', 'DZ'], China: ['Q148', 'CN'], 'Saudi Arabia': ['Q851', 'SA'],
  'United Arab Emirates': ['Q878', 'AE'], Qatar: ['Q846', 'QA'], Malaysia: ['Q833', 'MY'], Chile: ['Q298', 'CL'],
  Poland: ['Q36', 'PL'], Romania: ['Q218', 'RO'],
  Ukraine: ['Q212', 'UA'], Israel: ['Q801', 'IL'], Sudan: ['Q1049', 'SD'], Yemen: ['Q805', 'YE'], Iran: ['Q794', 'IR'],
  Lebanon: ['Q822', 'LB'], Syria: ['Q858', 'SY'], 'North Korea': ['Q423', 'KP'], Mali: ['Q912', 'ML'], Niger: ['Q1032', 'NE'],
  'Burkina Faso': ['Q965', 'BF'], 'Dem. Rep. Congo': ['Q974', 'CD'], Myanmar: ['Q836', 'MM'], Somalia: ['Q1045', 'SO'],
  Afghanistan: ['Q889', 'AF'], 'S. Sudan': ['Q958', 'SS'], Russia: ['Q159', 'RU'], Taiwan: ['Q865', 'TW'],
};

const QID_TO_COUNTRY = Object.fromEntries(Object.entries(ASSET_COUNTRIES).map(([name, [qid]]) => [qid, name]));
const COUNTRY_QIDS = [...new Set(Object.values(ASSET_COUNTRIES).map(([qid]) => qid))];
const COUNTRY_ISO2 = [...new Set(Object.values(ASSET_COUNTRIES).map(([, iso]) => iso))];

// ---------------------------------------------------------------------
// Source 1: Wikidata SPARQL — see README for the full story on this one.
// ---------------------------------------------------------------------

const SPARQL_ENDPOINT = 'https://query.wikidata.org/sparql';

// IMPORTANT (found the hard way, not assumed): SERVICE wikibase:label — the
// usual/"correct" way to get labels in a Wikidata SPARQL query — times out
// past Wikidata's own 60s limit once this query's VALUES/OPTIONAL shape is
// combined with it, even at LIMIT 200. Swapping it for a plain
// `?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en")` triple
// returns in well under a second for the same query at LIMIT 500, tested
// against every one of the 5 asset types including the broadest one (dam).
function buildWikidataListQuery(typeQid) {
  const values = COUNTRY_QIDS.map((q) => `wd:${q}`).join(' ');
  return `SELECT ?item ?itemLabel ?coord ?country WHERE {
    VALUES ?country { ${values} }
    ?item wdt:P31/wdt:P279* wd:${typeQid} .
    ?item wdt:P17 ?country .
    ?item wdt:P625 ?coord .
    ?item rdfs:label ?itemLabel .
    FILTER(LANG(?itemLabel) = "en")
  } LIMIT 800`;
}

// Per-facility detail — operator + commodities/materials produced — fetched
// lazily for a single clicked item, Wikidata items only (OSM/MRDS items
// carry everything they'll ever show directly in the bulk list — see below).
function buildWikidataDetailQuery(qid) {
  return `SELECT ?operatorLabel ?commodityLabel ?description WHERE {
    OPTIONAL { wd:${qid} wdt:P137 ?operator . ?operator rdfs:label ?operatorLabel . FILTER(LANG(?operatorLabel) = "en") }
    OPTIONAL { wd:${qid} wdt:P1056 ?commodity . ?commodity rdfs:label ?commodityLabel . FILTER(LANG(?commodityLabel) = "en") }
    OPTIONAL { wd:${qid} schema:description ?description . FILTER(LANG(?description) = "en") }
  }`;
}

function parseWktPoint(wkt) {
  const m = /Point\(([-\d.]+)\s+([-\d.]+)\)/.exec(wkt || '');
  if (!m) return [null, null];
  return [parseFloat(m[2]), parseFloat(m[1])]; // WKT is "Point(lon lat)"
}

async function sparqlFetch(query) {
  const url = `${SPARQL_ENDPOINT}?query=${encodeURIComponent(query)}&format=json`;
  const resp = await fetch(url, {
    headers: { 'User-Agent': USER_AGENT, Accept: 'application/sparql-results+json' },
    signal: AbortSignal.timeout(15000),
  });
  if (!resp.ok) throw new Error(`Wikidata query failed: ${resp.status}`);
  return resp.json();
}

async function fetchWikidata(key) {
  const { qid, label } = ASSET_TYPES[key];
  const data = await sparqlFetch(buildWikidataListQuery(qid));
  const rows = data.results?.bindings || [];

  const items = [];
  const seen = new Set();
  for (const row of rows) {
    const id = row.item.value.split('/').pop();
    if (seen.has(id)) continue; // an item can match P279* through more than one path
    seen.add(id);
    const [lat, lng] = parseWktPoint(row.coord?.value);
    if (lat == null || lng == null) continue;
    const countryQid = row.country.value.split('/').pop();
    items.push({
      id: `wd-${id}`,
      type: key,
      typeLabel: label,
      name: row.itemLabel?.value || id,
      lat,
      lng,
      country: QID_TO_COUNTRY[countryQid] || null,
      source: 'wikidata',
      wikidataId: id,
      wikidataUrl: `https://www.wikidata.org/wiki/${id}`,
    });
  }
  return items;
}

// ---------------------------------------------------------------------
// Source 2: OpenStreetMap via the Overpass API — supplements every type
// with crowd-mapped points that don't have a Wikidata item yet.
//
// Tags verified against the OSM wiki during development (not guessed):
// landuse=quarry / man_made=mineshaft for mines, industrial=port for
// ports, industrial=refinery for refineries (this one IS the documented
// tag, despite looking almost too simple), waterway=dam for dams. The one
// real correction made here: industrial=smelter does NOT exist as a tag
// (the wiki page 404s) — the actual convention is man_made=works with a
// product=* tag, so that's what's used below, narrowed to
// smelting-relevant products so it doesn't pull in unrelated factories.
//
// HONEST CAVEAT: I could not get a clean end-to-end test response from
// this specific sandbox against the public Overpass endpoint this session
// (one path hit a 406 from Apache content negotiation, another hit this
// tool's own robots.txt policy) — neither is evidence the live service is
// broken (it's one of the most widely used public geodata APIs there is,
// and a plain server-side fetch() like this route makes doesn't hit either
// obstacle), but it does mean this specific integration hasn't been
// smoke-tested end-to-end the way the Wikidata and MRDS queries were.
// Test it against a real deploy before trusting it blindly. It fails soft
// either way — a bad response here just means that layer shows fewer
// points, not a broken route (see the try/catch in fetchOsm below).
const OVERPASS_ENDPOINT = 'https://overpass-api.de/api/interpreter';

const OSM_FILTERS = {
  mine: ['nwr["landuse"="quarry"](area.a);', 'nwr["man_made"="mineshaft"](area.a);'],
  port: ['nwr["industrial"="port"](area.a);'],
  smelter: ['nwr["man_made"="works"]["product"~"steel|iron|aluminium|aluminum|copper|zinc|lead|nickel|tin",i](area.a);'],
  refinery: ['nwr["industrial"="refinery"](area.a);'],
  dam: ['nwr["waterway"="dam"](area.a);'],
};

// Sharded into 3 regional country-groups rather than one 46-country query —
// keeps each individual Overpass query (and the area index it has to build)
// smaller, and lets one slow/failed shard not take the others down with it.
const OSM_SHARDS = [
  ['IN', 'PK', 'BD', 'AF', 'CN', 'TW', 'TH', 'PH', 'MY', 'VN', 'MM', 'ID', 'SA', 'AE', 'QA', 'IL', 'IR', 'YE', 'LB', 'SY', 'TR', 'KP'],
  ['ZA', 'NG', 'EG', 'KE', 'ET', 'MA', 'DZ', 'ML', 'NE', 'BF', 'CD', 'SD', 'SS', 'SO'],
  ['UA', 'RU', 'PL', 'RO', 'BR', 'MX', 'AR', 'CO', 'PE', 'CL'],
];

function buildOverpassQuery(type, isoCodes) {
  const area = `area["ISO3166-1"~"^(${isoCodes.join('|')})$"]->.a;`;
  const body = OSM_FILTERS[type].join('');
  return `[out:json][timeout:20];${area}(${body});out center 200;`;
}

async function fetchOsmShard(type, isoCodes) {
  const query = buildOverpassQuery(type, isoCodes);
  const resp = await fetch(OVERPASS_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': USER_AGENT, Accept: 'application/json' },
    body: `data=${encodeURIComponent(query)}`,
    signal: AbortSignal.timeout(22000),
  });
  if (!resp.ok) throw new Error(`Overpass query failed: ${resp.status}`);
  const data = await resp.json();
  const { label } = ASSET_TYPES[type];
  return (data.elements || [])
    .map((el) => {
      const lat = el.lat ?? el.center?.lat;
      const lng = el.lon ?? el.center?.lon;
      const name = el.tags?.name || el.tags?.['name:en'];
      if (lat == null || lng == null || !name) return null; // unnamed points aren't useful for a click-to-inspect panel
      return {
        id: `osm-${el.type}-${el.id}`,
        type,
        typeLabel: label,
        name,
        lat,
        lng,
        country: null, // Overpass area filter already scoped this to our country list, but the union query doesn't tell us which one
        source: 'osm',
        osmUrl: `https://www.openstreetmap.org/${el.type}/${el.id}`,
      };
    })
    .filter(Boolean);
}

async function fetchOsm(type) {
  const results = await Promise.allSettled(OSM_SHARDS.map((iso) => fetchOsmShard(type, iso)));
  const items = [];
  const seen = new Set();
  for (const r of results) {
    if (r.status !== 'fulfilled') {
      console.error('Overpass shard failed:', r.reason?.message);
      continue; // one bad shard degrades coverage, doesn't fail the layer
    }
    for (const item of r.value) {
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      items.push(item);
    }
  }
  return items;
}

// ---------------------------------------------------------------------
// Source 3: USGS MRDS (mines only) — real, live, keyless OGC WFS service.
// Verified live 2026-08-31 by querying it directly: confirmed the real
// field names (dep_id, site_name, dev_stat, fips_code, code_list — NOT the
// richer schema you'd expect from the "flattened" bulk CSV download,
// which is a different, larger export this route doesn't use), and
// confirmed CQL_FILTER on country/fips_code is silently ignored by this
// deployment (always returns the same rows regardless of filter value) —
// so this uses BBOX spatial filtering instead, which was verified working
// (an India bbox correctly returned an India-coordinate mine, a Chile-area
// query without a bbox returned Chile). That also means results are scoped
// to a rough regional box, not exact country borders — see README.
//
// CRITICAL CAVEAT, stated plainly: USGS stopped systematically updating
// MRDS in 2011. This is real, historical global mine data, not live/fresh
// data — it supplements coverage, it doesn't replace Wikidata/OSM for
// anything current.
const MRDS_ENDPOINT = 'https://mrdata.usgs.gov/services/wfs/mrds';

// Rough regional bounding boxes (minLat,minLon,maxLat,maxLon) covering the
// tracked country list — MRDS has no reliable per-country filter (see
// above), so this is an intentional approximation, not a precise scope.
const MRDS_BBOXES = [
  { name: 'Asia + Middle East', box: '-11,25,55,150' },
  { name: 'Africa', box: '-35,-18,38,52' },
  { name: 'Europe + Russia', box: '40,15,75,180' },
  { name: 'Americas', box: '-56,-118,33,-34' },
];

// USGS commodity codes are terse (CU, AU, ...) — resolve the common ones to
// readable names; anything not in this table is shown as-is rather than
// guessed.
const MRDS_COMMODITY_NAMES = {
  CU: 'Copper', AU: 'Gold', AG: 'Silver', FE: 'Iron', PB: 'Lead', ZN: 'Zinc', NI: 'Nickel',
  CO: 'Cobalt', U: 'Uranium', COAL: 'Coal', SN: 'Tin', W: 'Tungsten', MO: 'Molybdenum',
  MN: 'Manganese', CR: 'Chromium', LI: 'Lithium', REE: 'Rare Earth Elements', DIAM: 'Diamond',
  PHOS: 'Phosphate', POTASH: 'Potash', BAUX: 'Bauxite', ASB: 'Asbestos', TALC: 'Talc',
  GYP: 'Gypsum', SALT: 'Salt', PGE: 'Platinum Group Elements',
};

function mrdsCommodityNames(codeList) {
  return (codeList || '')
    .split(/\s+/)
    .filter(Boolean)
    .map((c) => MRDS_COMMODITY_NAMES[c.toUpperCase()] || c)
    .filter((v, i, arr) => arr.indexOf(v) === i);
}

// Lightweight regex extraction of the fixed GML shape this WFS service
// returns — avoids pulling in a full XML/GML parsing dependency for one
// legacy source, same spirit as the hand-rolled CSV parser in
// ../power-plants/route.js.
function parseMrdsGml(xml) {
  const items = [];
  const memberRe = /<ms:mrds gml:id="([^"]+)">([\s\S]*?)<\/ms:mrds>/g;
  let m;
  while ((m = memberRe.exec(xml))) {
    const [, gmlId, block] = m;
    const pos = /<gml:pos>([-\d.]+)\s+([-\d.]+)<\/gml:pos>/.exec(block);
    const name = /<ms:site_name>([^<]*)<\/ms:site_name>/.exec(block);
    const devStat = /<ms:dev_stat>([^<]*)<\/ms:dev_stat>/.exec(block);
    const depId = /<ms:dep_id>([^<]*)<\/ms:dep_id>/.exec(block);
    const codeList = /<ms:code_list>([^<]*)<\/ms:code_list>/.exec(block);
    if (!pos || !name || !name[1].trim()) continue;
    items.push({
      id: `mrds-${gmlId}`,
      type: 'mine',
      typeLabel: ASSET_TYPES.mine.label,
      name: name[1].trim(),
      lat: parseFloat(pos[1]),
      lng: parseFloat(pos[2]),
      country: null, // see BBOX caveat above — not resolved to an exact tracked country
      source: 'usgs_mrds',
      devStatus: devStat ? devStat[1].trim() : null,
      commodities: mrdsCommodityNames(codeList ? codeList[1] : ''),
      mrdsUrl: depId ? `https://mrdata.usgs.gov/mrds/show-mrds.php?dep_id=${depId[1].trim()}` : null,
    });
  }
  return items;
}

async function fetchMrdsBbox({ box }) {
  const url = `${MRDS_ENDPOINT}?service=WFS&version=2.0.0&request=GetFeature&typeName=mrds&outputFormat=GML3&count=250&BBOX=${box}`;
  const resp = await fetch(url, { headers: { 'User-Agent': USER_AGENT }, signal: AbortSignal.timeout(20000) });
  if (!resp.ok) throw new Error(`MRDS query failed: ${resp.status}`);
  const xml = await resp.text();
  return parseMrdsGml(xml);
}

async function fetchMrds() {
  const results = await Promise.allSettled(MRDS_BBOXES.map(fetchMrdsBbox));
  const items = [];
  const seen = new Set();
  for (const r of results) {
    if (r.status !== 'fulfilled') {
      console.error('MRDS bbox query failed:', r.reason?.message);
      continue;
    }
    for (const item of r.value) {
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      items.push(item);
    }
  }
  return items;
}

// ---------------------------------------------------------------------
// Merge — Wikidata + OSM for every type, + MRDS for mines only. A simple
// proximity dedupe drops an OSM/MRDS point that's essentially the same
// facility as one Wikidata already has (within ~1km), so the same real
// mine doesn't show up as two overlapping markers.
// ---------------------------------------------------------------------

const DEDUPE_DEGREES = 0.01; // ~1km at the equator — good enough for this purpose, not geodesically precise

function dedupeAgainst(existing, candidates) {
  return candidates.filter(
    (c) => !existing.some((e) => Math.abs(e.lat - c.lat) < DEDUPE_DEGREES && Math.abs(e.lng - c.lng) < DEDUPE_DEGREES)
  );
}

async function fetchAssetType(key) {
  const [wikidataResult, osmResult, mrdsResult] = await Promise.allSettled([
    fetchWikidata(key),
    fetchOsm(key),
    key === 'mine' ? fetchMrds() : Promise.resolve([]),
  ]);

  const wikidata = wikidataResult.status === 'fulfilled' ? wikidataResult.value : [];
  if (wikidataResult.status === 'rejected') console.error(`Wikidata fetch failed for ${key}:`, wikidataResult.reason?.message);
  const osm = osmResult.status === 'fulfilled' ? osmResult.value : [];
  if (osmResult.status === 'rejected') console.error(`OSM fetch failed for ${key}:`, osmResult.reason?.message);
  const mrds = mrdsResult.status === 'fulfilled' ? mrdsResult.value : [];
  if (mrdsResult.status === 'rejected') console.error(`MRDS fetch failed for ${key}:`, mrdsResult.reason?.message);

  const merged = [...wikidata];
  merged.push(...dedupeAgainst(merged, osm));
  merged.push(...dedupeAgainst(merged, mrds));
  return merged;
}

// Per-type in-memory cache — best-effort, resets on cold start, not shared
// across serverless instances (same caveat as every other route here).
const cache = {};
const CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6h — refreshed regularly without hammering free shared endpoints

// Tiny detail cache too — a user re-opening the same asset panel shouldn't
// re-hit Wikidata every time. Wikidata items only — OSM/MRDS items carry
// everything they'll show directly in the bulk list already.
const detailCache = new Map();
const DETAIL_CACHE_TTL_MS = 6 * 60 * 60 * 1000;

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const detailId = searchParams.get('id'); // fetch enriched detail for one Wikidata QID
  const typeParam = searchParams.get('type'); // 'mine' | 'port' | 'smelter' | 'refinery' | 'dam' | omitted = all
  const country = searchParams.get('country');
  const q = searchParams.get('q');
  const limit = Number(searchParams.get('limit') || 1500);

  if (detailId) {
    try {
      const now = Date.now();
      const cached = detailCache.get(detailId);
      if (cached && now - cached.fetchedAt < DETAIL_CACHE_TTL_MS) {
        return NextResponse.json(cached.data);
      }
      const data = await sparqlFetch(buildWikidataDetailQuery(detailId));
      const rows = data.results?.bindings || [];
      const operator = rows.find((r) => r.operatorLabel)?.operatorLabel?.value || null;
      const commodities = [...new Set(rows.map((r) => r.commodityLabel?.value).filter(Boolean))];
      const description = rows.find((r) => r.description)?.description?.value || null;
      const result = { id: detailId, operator, commodities, description, wikidataUrl: `https://www.wikidata.org/wiki/${detailId}` };
      detailCache.set(detailId, { data: result, fetchedAt: now });
      return NextResponse.json(result);
    } catch (err) {
      console.error('Asset detail fetch failed:', err.message);
      return NextResponse.json({ id: detailId, operator: null, commodities: [], description: null, error: 'Failed to fetch detail' }, { status: 500 });
    }
  }

  const types = typeParam && ASSET_TYPES[typeParam] ? [typeParam] : Object.keys(ASSET_TYPES);

  try {
    const now = Date.now();
    await Promise.all(
      types.map(async (key) => {
        if (!cache[key] || now - cache[key].fetchedAt > CACHE_TTL_MS) {
          try {
            cache[key] = { items: await fetchAssetType(key), fetchedAt: now };
          } catch (err) {
            console.error(`Asset fetch failed for ${key}:`, err.message);
            if (!cache[key]) cache[key] = { items: [], fetchedAt: 0 }; // serve empty rather than 500 on a cold-start failure
          }
        }
      })
    );

    let items = types.flatMap((key) => cache[key].items);
    if (country) items = items.filter((a) => (a.country || '').toLowerCase() === country.toLowerCase());
    if (q) {
      const needle = q.toLowerCase();
      items = items.filter((a) => a.name.toLowerCase().includes(needle));
    }
    items = items.slice(0, limit);

    const oldestFetch = Math.min(...types.map((key) => cache[key]?.fetchedAt || 0));

    return NextResponse.json({
      source: 'Wikidata + OpenStreetMap (all types), USGS MRDS (mines)',
      sourceUrl: 'https://query.wikidata.org',
      note: "Three independent live sources merged and deduped — see README for exactly what each contributes and its real limitations (OSM coverage varies by region, MRDS is frozen since 2011).",
      types: Object.keys(ASSET_TYPES),
      countryScope: Object.keys(ASSET_COUNTRIES),
      fetchedAt: oldestFetch,
      count: items.length,
      items,
    });
  } catch (err) {
    console.error('Assets fetch failed:', err.message);
    return NextResponse.json({ error: 'Failed to fetch asset data', items: [] }, { status: 500 });
  }
}
