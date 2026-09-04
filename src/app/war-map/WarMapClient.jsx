'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import Link from 'next/link';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import * as topojson from 'topojson-client';
import worldTopology from 'world-atlas/countries-110m.json';

// ---------------------------------------------------------------------
// Data + color helpers
// ---------------------------------------------------------------------

const THREAT_COLORS = { critical: '#ff3b3b', high: '#ff9f1c', medium: '#ffd93d', low: '#4d9fff', stable: '#22323f' };
const threatColor = (t) => THREAT_COLORS[t] || THREAT_COLORS.low;

// Countries whose polygon links through to a curated conflicts.json
// write-up when clicked. Anything with a tier but no entry here (e.g.
// Russia, S. Sudan) still opens a lightweight generic panel.
const COUNTRY_TO_ZONE = {
  Ukraine: 'ukraine', Israel: 'gaza', Palestine: 'gaza', Sudan: 'sudan', Yemen: 'yemen',
  Iran: 'iran', Lebanon: 'lebanon', Syria: 'syria', 'North Korea': 'korea',
  Mali: 'sahel', Niger: 'sahel', 'Burkina Faso': 'sahel', 'Dem. Rep. Congo': 'drc',
  Myanmar: 'myanmar', Somalia: 'somalia', Afghanistan: 'afghanistan', Taiwan: 'taiwan-strait',
};

function timeAgo(iso) {
  if (!iso) return '';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function conflictsToGeoJSON(items) {
  return {
    type: 'FeatureCollection',
    features: items.map((c) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [c.lng, c.lat] },
      properties: { threat: c.threat, id: c.id },
    })),
  };
}

// The five Wikidata-backed asset layers (see /api/whitewatch/assets) — one
// checkbox each in the Layers panel, one marker color each on the globe.
const ASSET_LAYER_CONFIG = [
  { key: 'mine', label: 'Mines' },
  { key: 'port', label: 'Ports' },
  { key: 'smelter', label: 'Smelters' },
  { key: 'refinery', label: 'Refineries' },
  { key: 'dam', label: 'Dams' },
];

const MAP_STYLE = {
  version: 8,
  sources: {
    dark: { type: 'raster', tiles: ['https://basemaps.cartocdn.com/dark_matter_nolabels/{z}/{x}/{y}{r}.png'], tileSize: 256 },
    light: { type: 'raster', tiles: ['https://basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png'], tileSize: 256 },
    satellite: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256 },
    'terrain-dem': { type: 'raster-dem', tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'], tileSize: 256, encoding: 'terrarium' },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#05070a' } },
    { id: 'dark', type: 'raster', source: 'dark', layout: { visibility: 'visible' } },
    { id: 'light', type: 'raster', source: 'light', layout: { visibility: 'none' } },
    { id: 'satellite', type: 'raster', source: 'satellite', layout: { visibility: 'none' } },
  ],
};

// ---------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------

export default function WarMapClient() {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const assetMarkersRef = useRef([]);
  const layersInitRef = useRef(false);

  const [activeView, setActiveView] = useState('map');
  const [clock, setClock] = useState('--:--:-- UTC');
  const [mapLoaded, setMapLoaded] = useState(false);
  const [countriesLoaded, setCountriesLoaded] = useState(false);

  const [conflicts, setConflicts] = useState([]);
  const [countryThreat, setCountryThreat] = useState({});
  const [config, setConfig] = useState(null);

  const [activeThreatMap, setActiveThreatMap] = useState('all');
  const [activeBasemap, setActiveBasemap] = useState('dark');
  const [showMarkers, setShowMarkers] = useState(true);
  const [showHeat, setShowHeat] = useState(true);
  const [showCountries, setShowCountries] = useState(true);
  const [showTerrain, setShowTerrain] = useState(false);
  const [showPowerPlants, setShowPowerPlants] = useState(false);
  // One toggle per Wikidata asset layer — independently selectable on the
  // map, same idea as warwatchlive's own clickable mine/asset layers.
  const [activeAssetLayers, setActiveAssetLayers] = useState({});
  const [wikiAssets, setWikiAssets] = useState({});
  const [wikiAssetsLoading, setWikiAssetsLoading] = useState({});
  // NASA FIRMS active-fire + USGS earthquake point layers — one shared
  // endpoint (/api/whitewatch/hazards), two independent toggles.
  const [showFires, setShowFires] = useState(false);
  const [showQuakes, setShowQuakes] = useState(false);
  const [hazards, setHazards] = useState(null);
  const [hazardsLoading, setHazardsLoading] = useState(false);

  // Single inspector panel: either a conflict zone/country, or an
  // infrastructure asset (currently power plants; the same shape works for
  // mines/ports/smelters/refineries/dams once those layers exist).
  const [selectedItem, setSelectedItem] = useState(null); // { kind: 'zone' | 'asset', ... }

  const [feedItems, setFeedItems] = useState([]);
  const [feedQuery, setFeedQuery] = useState('');
  const [activeThreatFeed, setActiveThreatFeed] = useState('all');
  const [activeRegionFeed, setActiveRegionFeed] = useState('all');
  const [feedLoading, setFeedLoading] = useState(false);

  const [predictions, setPredictions] = useState(null);
  const [report, setReport] = useState(null);
  const [indicators, setIndicators] = useState(null);
  const [powerPlants, setPowerPlants] = useState(null);
  const [powerPlantsLoading, setPowerPlantsLoading] = useState(false);
  const [xFeed, setXFeed] = useState(null);
  const [commodities, setCommodities] = useState(null);

  // ---------------- Clock ----------------
  useEffect(() => {
    const tick = () => setClock(new Date().toUTCString().slice(17, 25) + ' UTC');
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // ---------------- Boot data fetch ----------------
  useEffect(() => {
    (async () => {
      try {
        const [c, cfg, ct] = await Promise.all([
          fetch('/api/whitewatch/conflicts').then((r) => r.json()),
          fetch('/api/whitewatch/config').then((r) => r.json()),
          fetch('/api/whitewatch/country-threat').then((r) => r.json()),
        ]);
        setConflicts(c.items || []);
        setConfig(cfg);
        setCountryThreat(ct || {});
      } catch (err) {
        console.error('Whitewatch: failed to load initial data', err);
      }
    })();
  }, []);

  // ---------------- Map init (once) ----------------
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE,
      center: [20, 20],
      zoom: 1.6,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right');
    map.on('load', () => {
      if (typeof map.setProjection === 'function') map.setProjection({ type: 'globe' });
      setMapLoaded(true);
    });
    map.on('style.load', () => {
      if (typeof map.setProjection === 'function') map.setProjection({ type: 'globe' });
    });
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // ---------------- Open a zone/country panel ----------------
  const openZone = useCallback((conflict) => {
    setSelectedItem({
      kind: 'zone',
      name: conflict.name,
      region: conflict.region,
      status: conflict.status,
      summary: conflict.summary,
      actors: conflict.actors || [],
      threat: conflict.threat,
    });
    const map = mapRef.current;
    if (map) map.flyTo({ center: [conflict.lng, conflict.lat], zoom: 3.5, duration: 900 });
  }, []);

  const openCountry = useCallback(
    (name) => {
      const zoneId = COUNTRY_TO_ZONE[name];
      if (zoneId) {
        const zone = conflicts.find((c) => c.id === zoneId);
        if (zone) {
          openZone(zone);
          return;
        }
      }
      const tier = countryThreat[name] || 'stable';
      setSelectedItem({
        kind: 'zone',
        name,
        region: 'Country-level assessment',
        status: tier === 'stable' ? 'No active conflict tracked' : 'Elevated',
        summary:
          tier === 'stable'
            ? `${name} has no active armed conflict in this dataset — every country carries a tier, and most default to stable.`
            : `${name} is flagged ${tier} for active conflict involvement. No dedicated write-up is curated for it yet.`,
        actors: [],
        threat: tier,
      });
    },
    [conflicts, countryThreat, openZone]
  );

  // ---------------- Open an infrastructure asset panel ----------------
  const openAsset = useCallback((plant) => {
    setSelectedItem({
      kind: 'asset',
      detailKind: 'powerplant',
      assetType: 'Power Plant',
      name: plant.name,
      country: plant.countryName,
      operator: plant.owner || 'Unlisted',
      fuel: plant.fuel,
      capacityMw: plant.capacityMw,
      commissioningYear: plant.commissioningYear,
    });
    const map = mapRef.current;
    if (map && plant.lat != null && plant.lng != null) {
      map.flyTo({ center: [plant.lng, plant.lat], zoom: 5, duration: 900 });
    }
  }, []);

  // ---------------- Open a Wikidata/OSM/MRDS asset panel (mine/port/smelter/refinery/dam) ----------------
  // /api/whitewatch/assets now merges three live sources per item.source:
  // 'wikidata' | 'osm' | 'usgs_mrds'. Only Wikidata items support the lazy
  // operator/commodities detail fetch (that's what keeps the bulk list
  // fast); OSM and MRDS items carry everything they'll ever show directly
  // in the bulk list already, so those just render immediately.
  const openWikiAsset = useCallback((asset) => {
    const SOURCE_LABEL = { wikidata: 'Wikidata', osm: 'OpenStreetMap', usgs_mrds: 'USGS MRDS (legacy, not updated since 2011)' };
    setSelectedItem({
      kind: 'asset',
      detailKind: 'wikidata',
      assetType: asset.typeLabel,
      name: asset.name,
      country: asset.country || 'Unknown',
      operator: null,
      commodities: asset.commodities || [],
      description: asset.devStatus ? `Status: ${asset.devStatus}` : null,
      detailLoading: asset.source === 'wikidata',
      sourceLabel: SOURCE_LABEL[asset.source] || 'Wikidata',
      sourceUrl: asset.wikidataUrl || asset.osmUrl || asset.mrdsUrl,
    });
    const map = mapRef.current;
    if (map && asset.lat != null && asset.lng != null) {
      map.flyTo({ center: [asset.lng, asset.lat], zoom: 6, duration: 900 });
    }
    if (asset.source !== 'wikidata') return; // OSM/MRDS items already have everything they'll show — no lazy fetch needed
    fetch(`/api/whitewatch/assets?id=${encodeURIComponent(asset.wikidataId)}`)
      .then((r) => r.json())
      .then((detail) => {
        setSelectedItem((prev) =>
          prev && prev.kind === 'asset' && prev.detailKind === 'wikidata' && prev.name === asset.name
            ? { ...prev, operator: detail.operator, commodities: detail.commodities || [], description: detail.description, detailLoading: false }
            : prev
        );
      })
      .catch((err) => {
        console.error('Whitewatch: asset detail load failed', err);
        setSelectedItem((prev) => (prev && prev.detailKind === 'wikidata' && prev.name === asset.name ? { ...prev, detailLoading: false } : prev));
      });
  }, []);

  // ---------------- Open a hazard panel (FIRMS fire detection or USGS earthquake) ----------------
  const openHazard = useCallback((item, hazardType) => {
    setSelectedItem({ kind: 'asset', detailKind: 'hazard', hazardType, ...item });
    const map = mapRef.current;
    if (map && item.lat != null && item.lng != null) {
      map.flyTo({ center: [item.lng, item.lat], zoom: 6, duration: 900 });
    }
  }, []);

  // ---------------- Markers (re-render on data or filter change) ----------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded || conflicts.length === 0) return;

    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    const filtered = conflicts.filter((c) => activeThreatMap === 'all' || c.threat === activeThreatMap);
    filtered.forEach((c) => {
      const el = document.createElement('div');
      el.className = `ww-zone-marker ww-threat-${c.threat}`;
      el.style.display = showMarkers ? '' : 'none';
      el.addEventListener('click', () => openZone(c));
      const marker = new maplibregl.Marker({ element: el }).setLngLat([c.lng, c.lat]).addTo(map);
      markersRef.current.push(marker);
    });

    if (map.getSource('conflicts')) {
      map.getSource('conflicts').setData(conflictsToGeoJSON(filtered));
    } else {
      map.addSource('conflicts', { type: 'geojson', data: conflictsToGeoJSON(filtered) });
      map.addLayer({
        id: 'conflict-heat',
        type: 'heatmap',
        source: 'conflicts',
        maxzoom: 9,
        paint: {
          'heatmap-weight': ['match', ['get', 'threat'], 'critical', 1, 'high', 0.7, 'medium', 0.4, 0.2],
          'heatmap-intensity': 1.1,
          'heatmap-radius': 55,
          'heatmap-opacity': showHeat ? 0.65 : 0,
          'heatmap-color': [
            'interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,0,0)',
            0.2, 'rgba(77,159,255,0.5)',
            0.4, 'rgba(255,217,61,0.6)',
            0.6, 'rgba(255,159,28,0.7)',
            1, 'rgba(255,59,59,0.9)',
          ],
        },
      });
    }
  }, [mapLoaded, conflicts, activeThreatMap, openZone]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    markersRef.current.forEach((m) => (m.getElement().style.display = showMarkers ? '' : 'none'));
  }, [showMarkers]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && map.getLayer('conflict-heat')) {
      map.setLayoutProperty('conflict-heat', 'visibility', showHeat ? 'visible' : 'none');
    }
  }, [showHeat, mapLoaded]);

  // ---------------- Country threat choropleth (once, after data ready) ----------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded || layersInitRef.current) return;
    if (Object.keys(countryThreat).length === 0) return;
    layersInitRef.current = true;

    try {
      const geo = topojson.feature(worldTopology, worldTopology.objects.countries);
      map.addSource('countries', { type: 'geojson', data: geo });

      const names = Object.keys(countryThreat);
      const fillColorExpr = ['match', ['get', 'name']];
      const fillOpacityExpr = ['match', ['get', 'name']];
      const lineWidthExpr = ['match', ['get', 'name']];
      names.forEach((name) => {
        const tier = countryThreat[name];
        fillColorExpr.push(name, threatColor(tier));
        fillOpacityExpr.push(name, 0.4);
        lineWidthExpr.push(name, 1.3);
      });
      fillColorExpr.push(THREAT_COLORS.stable);
      fillOpacityExpr.push(0.14);
      lineWidthExpr.push(0.4);

      const beforeId = map.getLayer('conflict-heat') ? 'conflict-heat' : undefined;
      map.addLayer({ id: 'countries-fill', type: 'fill', source: 'countries', paint: { 'fill-color': fillColorExpr, 'fill-opacity': fillOpacityExpr } }, beforeId);
      map.addLayer({ id: 'countries-line', type: 'line', source: 'countries', paint: { 'line-color': fillColorExpr, 'line-width': lineWidthExpr, 'line-opacity': 0.85 } }, beforeId);

      map.on('click', 'countries-fill', (e) => {
        if (e.features && e.features[0]) openCountry(e.features[0].properties.name);
      });
      map.on('mouseenter', 'countries-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'countries-fill', () => { map.getCanvas().style.cursor = ''; });

      setCountriesLoaded(true);
    } catch (err) {
      console.error('Whitewatch: country layer failed', err);
    }
  }, [mapLoaded, countryThreat, openCountry]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    ['countries-fill', 'countries-line'].forEach((id) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', showCountries ? 'visible' : 'none');
    });
  }, [showCountries, countriesLoaded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    ['dark', 'light', 'satellite'].forEach((id) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', id === activeBasemap ? 'visible' : 'none');
    });
  }, [activeBasemap]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoaded) return;
    if (showTerrain) {
      if (map.getSource('terrain-dem')) map.setTerrain({ source: 'terrain-dem', exaggeration: 1.4 });
    } else {
      map.setTerrain(null);
    }
  }, [showTerrain, mapLoaded]);

  // ---------------- Power plant assets (fetched lazily, first time needed) ----------------
  const loadPowerPlants = useCallback(() => {
    if (powerPlants || powerPlantsLoading) return;
    setPowerPlantsLoading(true);
    fetch('/api/whitewatch/power-plants')
      .then((r) => r.json())
      .then(setPowerPlants)
      .catch((err) => console.error('Whitewatch: power plants load failed', err))
      .finally(() => setPowerPlantsLoading(false));
  }, [powerPlants, powerPlantsLoading]);

  useEffect(() => {
    if (showPowerPlants || activeView === 'indicators') loadPowerPlants();
  }, [showPowerPlants, activeView, loadPowerPlants]);

  // Plot power-plant markers on the globe once data + toggle are both on.
  useEffect(() => {
    const map = mapRef.current;
    assetMarkersRef.current.forEach((m) => m.remove());
    assetMarkersRef.current = [];
    if (!map || !mapLoaded || !showPowerPlants || !powerPlants?.items) return;

    powerPlants.items.forEach((p) => {
      if (p.lat == null || p.lng == null) return;
      const el = document.createElement('div');
      el.className = 'ww-asset-marker ww-asset-power';
      el.title = `${p.name} — ${p.capacityMw.toLocaleString()} MW`;
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        openAsset(p);
      });
      const marker = new maplibregl.Marker({ element: el }).setLngLat([p.lng, p.lat]).addTo(map);
      assetMarkersRef.current.push(marker);
    });
  }, [mapLoaded, showPowerPlants, powerPlants, openAsset]);

  // ---------------- Wikidata asset layers (mines/ports/smelters/refineries/dams) ----------------
  const loadWikiAssetType = useCallback(
    (type) => {
      if (wikiAssets[type] || wikiAssetsLoading[type]) return;
      setWikiAssetsLoading((prev) => ({ ...prev, [type]: true }));
      fetch(`/api/whitewatch/assets?type=${type}`)
        .then((r) => r.json())
        .then((data) => setWikiAssets((prev) => ({ ...prev, [type]: data })))
        .catch((err) => console.error(`Whitewatch: ${type} layer load failed`, err))
        .finally(() => setWikiAssetsLoading((prev) => ({ ...prev, [type]: false })));
    },
    [wikiAssets, wikiAssetsLoading]
  );

  useEffect(() => {
    ASSET_LAYER_CONFIG.forEach(({ key }) => {
      if (activeAssetLayers[key]) loadWikiAssetType(key);
    });
  }, [activeAssetLayers, loadWikiAssetType]);

  const wikiAssetMarkersRef = useRef([]);
  useEffect(() => {
    const map = mapRef.current;
    wikiAssetMarkersRef.current.forEach((m) => m.remove());
    wikiAssetMarkersRef.current = [];
    if (!map || !mapLoaded) return;

    ASSET_LAYER_CONFIG.forEach(({ key }) => {
      if (!activeAssetLayers[key] || !wikiAssets[key]?.items) return;
      wikiAssets[key].items.forEach((asset) => {
        if (asset.lat == null || asset.lng == null) return;
        const el = document.createElement('div');
        el.className = `ww-asset-marker ww-asset-${key}`;
        el.title = `${asset.name}${asset.country ? ` — ${asset.country}` : ''}`;
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          openWikiAsset(asset);
        });
        const marker = new maplibregl.Marker({ element: el }).setLngLat([asset.lng, asset.lat]).addTo(map);
        wikiAssetMarkersRef.current.push(marker);
      });
    });
  }, [mapLoaded, activeAssetLayers, wikiAssets, openWikiAsset]);

  // ---------------- Hazard layers (NASA FIRMS fires + USGS earthquakes) ----------------
  const loadHazards = useCallback(() => {
    if (hazards || hazardsLoading) return;
    setHazardsLoading(true);
    fetch('/api/whitewatch/hazards')
      .then((r) => r.json())
      .then(setHazards)
      .catch((err) => console.error('Whitewatch: hazards load failed', err))
      .finally(() => setHazardsLoading(false));
  }, [hazards, hazardsLoading]);

  useEffect(() => {
    if (showFires || showQuakes) loadHazards();
  }, [showFires, showQuakes, loadHazards]);

  const hazardMarkersRef = useRef([]);
  useEffect(() => {
    const map = mapRef.current;
    hazardMarkersRef.current.forEach((m) => m.remove());
    hazardMarkersRef.current = [];
    if (!map || !mapLoaded) return;

    if (showFires && hazards?.fires?.items) {
      hazards.fires.items.forEach((f) => {
        if (f.lat == null || f.lng == null) return;
        const el = document.createElement('div');
        el.className = 'ww-asset-marker ww-asset-fire';
        el.title = `Fire detection${f.confidence ? ` — confidence ${f.confidence}` : ''}${f.acqDate ? ` — ${f.acqDate}` : ''}`;
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          openHazard(f, 'fire');
        });
        const marker = new maplibregl.Marker({ element: el }).setLngLat([f.lng, f.lat]).addTo(map);
        hazardMarkersRef.current.push(marker);
      });
    }

    if (showQuakes && hazards?.quakes?.items) {
      hazards.quakes.items.forEach((q) => {
        if (q.lat == null || q.lng == null) return;
        const el = document.createElement('div');
        el.className = 'ww-asset-marker ww-asset-quake';
        el.title = `M${q.mag} — ${q.place || 'Unknown location'}`;
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          openHazard(q, 'quake');
        });
        const marker = new maplibregl.Marker({ element: el }).setLngLat([q.lng, q.lat]).addTo(map);
        hazardMarkersRef.current.push(marker);
      });
    }
  }, [mapLoaded, showFires, showQuakes, hazards, openHazard]);

  // ---------------- Intel Feed ----------------
  const loadFeed = useCallback(async () => {
    setFeedLoading(true);
    try {
      const params = new URLSearchParams();
      if (activeThreatFeed !== 'all') params.set('threat', activeThreatFeed);
      if (activeRegionFeed !== 'all') params.set('region', activeRegionFeed);
      if (feedQuery) params.set('q', feedQuery);
      const data = await fetch(`/api/whitewatch/news?${params.toString()}`).then((r) => r.json());
      setFeedItems(data.items || []);
    } catch (err) {
      console.error('Whitewatch: feed load failed', err);
      setFeedItems([]);
    } finally {
      setFeedLoading(false);
    }
  }, [activeThreatFeed, activeRegionFeed, feedQuery]);

  useEffect(() => {
    if (activeView === 'feed') {
      loadFeed();
      if (!xFeed) fetch('/api/whitewatch/x-feed').then((r) => r.json()).then(setXFeed).catch((err) => console.error(err));
    }
  }, [activeView, activeThreatFeed, activeRegionFeed]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------- Predictions ----------------
  useEffect(() => {
    if (activeView !== 'predictions' || predictions) return;
    fetch('/api/whitewatch/predictions').then((r) => r.json()).then(setPredictions).catch((err) => console.error(err));
  }, [activeView]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------- Daily Report ----------------
  useEffect(() => {
    if (activeView !== 'report' || report) return;
    fetch('/api/whitewatch/report').then((r) => r.json()).then(setReport).catch((err) => console.error(err));
  }, [activeView]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------- Global Indicators (World Bank + IMF + UNHCR) ----------------
  useEffect(() => {
    if (activeView !== 'indicators' || indicators) return;
    fetch('/api/whitewatch/indicators').then((r) => r.json()).then(setIndicators).catch((err) => console.error(err));
  }, [activeView]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------- Commodities ticker (FRED) ----------------
  useEffect(() => {
    if (activeView !== 'dashboard' || commodities) return;
    fetch('/api/whitewatch/commodities').then((r) => r.json()).then(setCommodities).catch((err) => console.error(err));
  }, [activeView]); // eslint-disable-line react-hooks/exhaustive-deps

  // -----------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------

  return (
    <div className="ww-root">
      <style>{CSS}</style>

      <div className="ww-desktop-notice">This desk is built for a laptop/desktop screen — some panels will feel tight in a narrow phone browser.</div>

      <header className="ww-topbar">
        <div className="ww-brand">
          <Link href="/dashboard" className="ww-back-link">← Whitewater</Link>
          <span className="ww-brand-dot" />
          <span className="ww-brand-name">WHITEWATCH</span>
        </div>
        <nav className="ww-tabs">
          {['map', 'feed', 'indicators', 'predictions', 'report', 'dashboard'].map((v) => (
            <button key={v} className={`ww-tab ${activeView === v ? 'ww-active' : ''}`} onClick={() => setActiveView(v)}>
              {
                {
                  map: 'War Map',
                  feed: 'Intel Feed',
                  indicators: 'Indicators',
                  predictions: 'Predictions',
                  report: 'Daily Report',
                  dashboard: 'Dashboard',
                }[v]
              }
            </button>
          ))}
        </nav>
        <div className="ww-topbar-right">
          <span className="ww-live-dot" /> <span className="ww-live-label">LIVE</span>
          <span className="ww-clock">{clock}</span>
        </div>
      </header>

      <main className="ww-main">
        {activeView === 'map' && (
          <div className="ww-view ww-map-view">
            <aside className="ww-side-feed">
              <div className="ww-panel-title">Latest News</div>
              <MiniFeed />
              <div className="ww-panel-title ww-spaced-lg">Live Stream — Bloomberg Originals</div>
              <div className="ww-live-embed-wrap ww-live-embed-wrap-mini">
                <iframe
                  className="ww-live-embed"
                  src="https://www.youtube.com/embed/live_stream?channel=UCUMZ7gohGI9HcU9VNsr2FJQ&autoplay=0"
                  title="Bloomberg Originals live"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                />
              </div>
              <div className="ww-muted ww-mini-caption">Bloomberg's own free public livestream — not paywalled, not scraped.</div>
            </aside>

            <div className="ww-map-stage">
              <div ref={mapContainerRef} className="ww-globe" />

              {!mapLoaded && (
                <div className="ww-map-loading">
                  <div className="ww-spinner" />
                  <div>INITIALIZING GLOBE…</div>
                </div>
              )}

              <div className="ww-panel ww-panel-layers">
                <div className="ww-panel-title">Basemap</div>
                <div className="ww-chip-row">
                  {['dark', 'satellite', 'light'].map((s) => (
                    <button key={s} className={`ww-chip ${activeBasemap === s ? 'ww-active' : ''}`} onClick={() => setActiveBasemap(s)}>
                      {s[0].toUpperCase() + s.slice(1)}
                    </button>
                  ))}
                </div>
                <div className="ww-panel-title ww-spaced">Layers</div>
                <label className="ww-toggle-row"><input type="checkbox" checked={showCountries} onChange={(e) => setShowCountries(e.target.checked)} /> Country threat</label>
                <label className="ww-toggle-row"><input type="checkbox" checked={showMarkers} onChange={(e) => setShowMarkers(e.target.checked)} /> Conflict zones</label>
                <label className="ww-toggle-row"><input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} /> Threat heatmap</label>
                <label className="ww-toggle-row"><input type="checkbox" checked={showTerrain} onChange={(e) => setShowTerrain(e.target.checked)} /> 3D terrain</label>
                <label className="ww-toggle-row">
                  <input type="checkbox" checked={showPowerPlants} onChange={(e) => setShowPowerPlants(e.target.checked)} /> Power plants
                  {powerPlantsLoading && <span className="ww-muted-inline"> loading…</span>}
                </label>
                {ASSET_LAYER_CONFIG.map(({ key, label }) => (
                  <label key={key} className="ww-toggle-row">
                    <input
                      type="checkbox"
                      checked={Boolean(activeAssetLayers[key])}
                      onChange={(e) => setActiveAssetLayers((prev) => ({ ...prev, [key]: e.target.checked }))}
                    />{' '}
                    <span className={`ww-asset-swatch ww-asset-${key}`} /> {label}
                    {wikiAssetsLoading[key] && <span className="ww-muted-inline"> loading…</span>}
                    {wikiAssets[key] && <span className="ww-muted-inline"> ({wikiAssets[key].count})</span>}
                  </label>
                ))}
                <label className="ww-toggle-row">
                  <input type="checkbox" checked={showFires} onChange={(e) => setShowFires(e.target.checked)} />{' '}
                  <span className="ww-asset-swatch ww-asset-fire" /> Active fires (FIRMS)
                  {hazardsLoading && <span className="ww-muted-inline"> loading…</span>}
                  {hazards?.fires && !hazards.fires.live && <span className="ww-muted-inline"> (needs FIRMS_MAP_KEY)</span>}
                  {hazards?.fires?.live && <span className="ww-muted-inline"> ({hazards.fires.count})</span>}
                </label>
                <label className="ww-toggle-row">
                  <input type="checkbox" checked={showQuakes} onChange={(e) => setShowQuakes(e.target.checked)} />{' '}
                  <span className="ww-asset-swatch ww-asset-quake" /> Earthquakes (USGS)
                  {hazardsLoading && <span className="ww-muted-inline"> loading…</span>}
                  {hazards?.quakes?.live && <span className="ww-muted-inline"> ({hazards.quakes.count})</span>}
                </label>
                <div className="ww-panel-title ww-spaced">Threat filter</div>
                <div className="ww-chip-row">
                  {['all', 'critical', 'high', 'medium'].map((t) => (
                    <button key={t} className={`ww-chip ww-threat-${t} ${activeThreatMap === t ? 'ww-active' : ''}`} onClick={() => setActiveThreatMap(t)}>
                      {t === 'all' ? 'All' : t[0].toUpperCase() + t.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              {selectedItem && selectedItem.kind === 'zone' && (
                <div className="ww-panel ww-panel-intel">
                  <button className="ww-close-btn" onClick={() => setSelectedItem(null)}>&times;</button>
                  <div className={`ww-zone-badge ww-threat-${selectedItem.threat}`}>{selectedItem.threat.toUpperCase()}</div>
                  <h2 className="ww-zone-name">{selectedItem.name}</h2>
                  <div className="ww-zone-region">{selectedItem.region}</div>
                  <div className="ww-zone-status">{selectedItem.status}</div>
                  <p className="ww-zone-summary">{selectedItem.summary}</p>
                  {selectedItem.actors.length > 0 && (
                    <div className="ww-zone-actors">
                      {selectedItem.actors.map((a) => <span key={a}>{a}</span>)}
                    </div>
                  )}
                </div>
              )}

              {selectedItem && selectedItem.kind === 'asset' && selectedItem.detailKind === 'powerplant' && (
                <div className="ww-panel ww-panel-intel">
                  <button className="ww-close-btn" onClick={() => setSelectedItem(null)}>&times;</button>
                  <div className="ww-zone-badge ww-asset-badge">{selectedItem.assetType.toUpperCase()}</div>
                  <h2 className="ww-zone-name">{selectedItem.name}</h2>
                  <div className="ww-zone-region">{selectedItem.country}</div>
                  <div className="ww-asset-fields">
                    <div className="ww-asset-field"><span>OPERATOR</span><b>{selectedItem.operator}</b></div>
                    <div className="ww-asset-field"><span>FUEL</span><b>{selectedItem.fuel}</b></div>
                    <div className="ww-asset-field"><span>CAPACITY</span><b>{selectedItem.capacityMw.toLocaleString()} MW</b></div>
                    {selectedItem.commissioningYear && (
                      <div className="ww-asset-field"><span>COMMISSIONED</span><b>{selectedItem.commissioningYear}</b></div>
                    )}
                  </div>
                  <p className="ww-zone-summary ww-asset-source">Source: Global Power Plant Database (WRI, CC BY 4.0)</p>
                </div>
              )}

              {selectedItem && selectedItem.kind === 'asset' && selectedItem.detailKind === 'wikidata' && (
                <div className="ww-panel ww-panel-intel">
                  <button className="ww-close-btn" onClick={() => setSelectedItem(null)}>&times;</button>
                  <div className="ww-zone-badge ww-asset-badge">{selectedItem.assetType.toUpperCase()}</div>
                  <h2 className="ww-zone-name">{selectedItem.name}</h2>
                  <div className="ww-zone-region">{selectedItem.country}</div>
                  {selectedItem.description && <p className="ww-zone-summary">{selectedItem.description}</p>}
                  <div className="ww-asset-fields">
                    <div className="ww-asset-field">
                      <span>OPERATOR</span>
                      <b>{selectedItem.detailLoading ? 'Loading…' : selectedItem.operator || 'Not listed'}</b>
                    </div>
                    <div className="ww-asset-field">
                      <span>COMMODITIES</span>
                      <b>{selectedItem.detailLoading ? 'Loading…' : selectedItem.commodities.length ? selectedItem.commodities.join(', ') : 'Not listed'}</b>
                    </div>
                  </div>
                  <p className="ww-zone-summary ww-asset-source">
                    Source:{' '}
                    {selectedItem.sourceUrl ? (
                      <a href={selectedItem.sourceUrl} target="_blank" rel="noopener noreferrer">{selectedItem.sourceLabel}</a>
                    ) : (
                      selectedItem.sourceLabel
                    )}
                    {' — not every facility has every field filled in.'}
                  </p>
                </div>
              )}

              {selectedItem && selectedItem.kind === 'asset' && selectedItem.detailKind === 'hazard' && selectedItem.hazardType === 'fire' && (
                <div className="ww-panel ww-panel-intel">
                  <button className="ww-close-btn" onClick={() => setSelectedItem(null)}>&times;</button>
                  <div className="ww-zone-badge ww-asset-badge">FIRE DETECTION</div>
                  <h2 className="ww-zone-name">{selectedItem.acqDate || 'Recent'} {selectedItem.acqTime ? `${String(selectedItem.acqTime).padStart(4, '0').slice(0, 2)}:${String(selectedItem.acqTime).padStart(4, '0').slice(2)} UTC` : ''}</h2>
                  <div className="ww-asset-fields">
                    <div className="ww-asset-field"><span>CONFIDENCE</span><b>{selectedItem.confidence ?? 'Unknown'}</b></div>
                    <div className="ww-asset-field"><span>BRIGHTNESS</span><b>{selectedItem.brightness != null ? `${selectedItem.brightness} K` : '—'}</b></div>
                    <div className="ww-asset-field"><span>RADIATIVE POWER</span><b>{selectedItem.frp != null ? `${selectedItem.frp} MW` : '—'}</b></div>
                    {selectedItem.satellite && <div className="ww-asset-field"><span>SATELLITE</span><b>{selectedItem.satellite}</b></div>}
                  </div>
                  <p className="ww-zone-summary ww-asset-source">Source: NASA FIRMS (thermal-anomaly detection, not confirmed fire/damage assessment).</p>
                </div>
              )}

              {selectedItem && selectedItem.kind === 'asset' && selectedItem.detailKind === 'hazard' && selectedItem.hazardType === 'quake' && (
                <div className="ww-panel ww-panel-intel">
                  <button className="ww-close-btn" onClick={() => setSelectedItem(null)}>&times;</button>
                  <div className="ww-zone-badge ww-asset-badge">M{selectedItem.mag} EARTHQUAKE</div>
                  <h2 className="ww-zone-name">{selectedItem.place || 'Unknown location'}</h2>
                  <div className="ww-zone-region">{selectedItem.time ? timeAgo(selectedItem.time) : ''}</div>
                  <div className="ww-asset-fields">
                    <div className="ww-asset-field"><span>MAGNITUDE</span><b>{selectedItem.mag} {selectedItem.magType}</b></div>
                    <div className="ww-asset-field"><span>DEPTH</span><b>{selectedItem.depthKm != null ? `${selectedItem.depthKm} km` : '—'}</b></div>
                    {selectedItem.alert && <div className="ww-asset-field"><span>PAGER ALERT</span><b>{selectedItem.alert.toUpperCase()}</b></div>}
                    {selectedItem.tsunami && <div className="ww-asset-field"><span>TSUNAMI</span><b>Advisory issued</b></div>}
                  </div>
                  <p className="ww-zone-summary ww-asset-source">
                    Source:{' '}
                    {selectedItem.url ? <a href={selectedItem.url} target="_blank" rel="noopener noreferrer">USGS Earthquake Hazards Program</a> : 'USGS Earthquake Hazards Program'}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {activeView === 'feed' && (
          <div className="ww-view ww-section">
            <div className="ww-feed-toolbar">
              <input className="ww-search" placeholder="Search intel feed…" value={feedQuery} onChange={(e) => setFeedQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && loadFeed()} />
              <button className="ww-refresh-btn" onClick={loadFeed}>Refresh</button>
            </div>
            <div className="ww-chip-row ww-spaced-sm">
              {['all', 'critical', 'high', 'medium', 'low'].map((t) => (
                <button key={t} className={`ww-chip ww-threat-${t} ${activeThreatFeed === t ? 'ww-active' : ''}`} onClick={() => setActiveThreatFeed(t)}>
                  {t === 'all' ? 'All threat' : t[0].toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
            <div className="ww-chip-row ww-spaced-sm">
              {['all', 'Middle East', 'Europe', 'East Asia', 'South Asia', 'Southeast Asia', 'Africa', 'Americas', 'Global'].map((r) => (
                <button key={r} className={`ww-chip ${activeRegionFeed === r ? 'ww-active' : ''}`} onClick={() => setActiveRegionFeed(r)}>
                  {r === 'all' ? 'All regions' : r}
                </button>
              ))}
            </div>

            {!feedLoading && feedItems.length > 0 && (
              <a className="ww-hero-card" href={feedItems[0].link} target="_blank" rel="noopener noreferrer">
                {feedItems[0].image && <img className="ww-hero-image" src={feedItems[0].image} alt="" onError={(e) => { e.currentTarget.style.display = 'none'; }} />}
                <div className={`ww-hero-badge ww-threat-${feedItems[0].threat}`}>{feedItems[0].threat.toUpperCase()}</div>
                <h2 className="ww-hero-title">{feedItems[0].title}</h2>
                <div className="ww-hero-meta">{feedItems[0].source} · {feedItems[0].region} · {timeAgo(feedItems[0].publishedAt)}</div>
              </a>
            )}

            <div className="ww-feed-grid">
              {feedLoading && <div className="ww-muted">Loading…</div>}
              {!feedLoading && feedItems.length === 0 && <div className="ww-muted">No items yet.</div>}
              {feedItems.slice(1).map((item) => <FeedCard key={item.id || item.link} item={item} />)}
            </div>

            <p className="ww-eyebrow ww-spaced-lg">X</p>
            <h2 className="ww-h2">{xFeed?.live ? 'Live search results' : 'Not connected yet'}</h2>
            <p className="ww-muted">{xFeed?.note}</p>
            <div className="ww-card-list">
              {(xFeed?.items || []).map((t) => (
                <a key={t.id} className="ww-card ww-card-link" href={t.link} target="_blank" rel="noopener noreferrer">
                  <div className="ww-card-top">
                    <span className="ww-card-name">{t.author}</span>
                    <span className="ww-muted-inline">{timeAgo(t.createdAt)}</span>
                  </div>
                  <div className="ww-card-body">{t.text}</div>
                </a>
              ))}
              {xFeed?.live && xFeed.items.length === 0 && <div className="ww-muted">No matching posts right now.</div>}
            </div>
          </div>
        )}

        {activeView === 'indicators' && (
          <div className="ww-view ww-section">
            <p className="ww-eyebrow">Global Indicators</p>
            <h1>Energy, water, economy & displacement</h1>
            <p className="ww-muted">
              {indicators?.note || 'Loading World Bank / IMF / UNHCR data…'}
            </p>
            <p className="ww-muted-inline">{indicators?.source}</p>
            <div className="ww-table-wrap">
              <table className="ww-table">
                <thead>
                  <tr>
                    <th>Country</th>
                    <th>Energy use / capita</th>
                    <th>Electricity access</th>
                    <th>Freshwater withdrawal</th>
                    <th>GDP growth</th>
                    <th>Inflation</th>
                    <th>Refugees (origin)</th>
                    <th>IDPs</th>
                  </tr>
                </thead>
                <tbody>
                  {(indicators?.items || []).map((row) => (
                    <tr key={row.iso3}>
                      <td>{row.country}</td>
                      <td>
                        {row.energyUsePerCapitaKgOilEq != null ? `${Math.round(row.energyUsePerCapitaKgOilEq)} kg oil eq.` : '—'}
                        {row.energyUsePerCapitaYear && <span className="ww-muted-inline"> ({row.energyUsePerCapitaYear})</span>}
                      </td>
                      <td>
                        {row.electricAccessPct != null ? `${row.electricAccessPct.toFixed(1)}%` : '—'}
                        {row.electricAccessYear && <span className="ww-muted-inline"> ({row.electricAccessYear})</span>}
                      </td>
                      <td>
                        {row.freshwaterWithdrawalBillionM3 != null ? `${row.freshwaterWithdrawalBillionM3.toFixed(1)} bn m³/yr` : '—'}
                        {row.freshwaterWithdrawalYear && <span className="ww-muted-inline"> ({row.freshwaterWithdrawalYear})</span>}
                      </td>
                      <td className={row.gdpGrowthPct != null && row.gdpGrowthPct < 0 ? 'ww-neg' : undefined}>
                        {row.gdpGrowthPct != null ? `${row.gdpGrowthPct.toFixed(1)}%` : '—'}
                        {row.gdpGrowthYear && <span className="ww-muted-inline"> ({row.gdpGrowthYear})</span>}
                      </td>
                      <td className={row.inflationPct != null && row.inflationPct > 10 ? 'ww-neg' : undefined}>
                        {row.inflationPct != null ? `${row.inflationPct.toFixed(1)}%` : '—'}
                        {row.inflationYear && <span className="ww-muted-inline"> ({row.inflationYear})</span>}
                      </td>
                      <td>
                        {row.refugeesOrigin != null ? row.refugeesOrigin.toLocaleString() : '—'}
                        {row.displacementYear && <span className="ww-muted-inline"> ({row.displacementYear})</span>}
                      </td>
                      <td>{row.idps != null ? row.idps.toLocaleString() : '—'}</td>
                    </tr>
                  ))}
                  {indicators && indicators.items.length === 0 && (
                    <tr><td colSpan={8} className="ww-muted">No data returned.</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <p className="ww-eyebrow ww-spaced-lg">Power Plants</p>
            <h2 className="ww-h2">Major plants in emerging markets — also plotted on the War Map (toggle "Power plants" in Layers)</h2>
            <p className="ww-muted">{powerPlants?.source || 'Loading…'}{powerPlants?.scope ? ` — ${powerPlants.scope}` : ''}</p>
            <div className="ww-card-list">
              {(powerPlants?.items || []).slice(0, 25).map((p) => (
                <div key={`${p.country}-${p.name}`} className="ww-card ww-card-link" onClick={() => { setActiveView('map'); setShowPowerPlants(true); openAsset(p); }}>
                  <div className="ww-card-top">
                    <span className="ww-card-name">{p.name}</span>
                    <span className="ww-pill">{p.fuel}</span>
                  </div>
                  <div className="ww-card-body">
                    {p.countryName} · {p.capacityMw.toLocaleString()} MW
                    {p.commissioningYear ? ` · commissioned ${p.commissioningYear}` : ''}
                  </div>
                </div>
              ))}
              {powerPlants && powerPlants.items.length === 0 && <div className="ww-muted">No plants matched.</div>}
            </div>

            {ASSET_LAYER_CONFIG.map(({ key, label }) => (
              <div key={key}>
                <p className="ww-eyebrow ww-spaced-lg">{label}</p>
                <h2 className="ww-h2">
                  Live from Wikidata — click one below or toggle "{label}" in the War Map's Layers panel
                </h2>
                <p className="ww-muted">{wikiAssets[key]?.source || (wikiAssetsLoading[key] ? 'Loading…' : 'Not loaded yet — toggle the layer on the map, or click a row below')}</p>
                <div className="ww-card-list">
                  {(wikiAssets[key]?.items || []).slice(0, 15).map((a) => (
                    <div
                      key={a.id}
                      className="ww-card ww-card-link"
                      onClick={() => {
                        setActiveAssetLayers((prev) => ({ ...prev, [key]: true }));
                        setActiveView('map');
                        openWikiAsset(a);
                      }}
                    >
                      <div className="ww-card-top">
                        <span className="ww-card-name">{a.name}</span>
                        <span className={`ww-pill ww-asset-pill ww-asset-${key}`}>{a.typeLabel}</span>
                      </div>
                      <div className="ww-card-body">{a.country || 'Unknown country'}</div>
                    </div>
                  ))}
                  {!wikiAssets[key] && !wikiAssetsLoading[key] && (
                    <div className="ww-card ww-card-link" onClick={() => setActiveAssetLayers((prev) => ({ ...prev, [key]: true }))}>
                      <div className="ww-card-body ww-muted">Click to load {label.toLowerCase()}…</div>
                    </div>
                  )}
                  {wikiAssets[key] && wikiAssets[key].items.length === 0 && <div className="ww-muted">No {label.toLowerCase()} matched in scope.</div>}
                </div>
              </div>
            ))}
            <p className="ww-muted ww-spaced-sm">
              Source: Wikidata Query Service (CC0), the same source warwatchlive's own asset panel cites — community-maintained
              and genuinely global, but coverage per country/facility depends on what's been mapped there. Scoped to the same
              emerging-market + active-conflict-zone country list as the rest of this dashboard; widen it in
              <code> app/api/whitewatch/assets/route.js</code>.
            </p>
          </div>
        )}

        {activeView === 'predictions' && (
          <div className="ww-view ww-section">
            <p className="ww-eyebrow">Predictions</p>
            <h1>7-day outlook</h1>
            <p className="ww-muted">{predictions?.note || (predictions?.live ? 'Live AI-generated outlook.' : 'Loading…')}</p>
            <div className="ww-card-list">
              {Array.isArray(predictions?.items) &&
                predictions.items.map((p) => (
                  <div key={p.id || p.name} className="ww-card">
                    <div className="ww-card-top"><span className="ww-card-name">{p.name}</span> <span className={`ww-pill ww-threat-${p.threat}`}>{p.threat}</span></div>
                    <div className="ww-card-body">{p.outlook}</div>
                  </div>
                ))}
              {predictions && !Array.isArray(predictions.items) && (
                <div className="ww-card"><pre className="ww-card-body">{predictions.items}</pre></div>
              )}
            </div>
          </div>
        )}

        {activeView === 'report' && (
          <div className="ww-view ww-section">
            <p className="ww-eyebrow">{report ? new Date(report.generatedAt).toLocaleString() : '—'}</p>
            <h1>War Daily Report</h1>
            {report && (
              <>
                <div className="ww-stat-row">
                  {Object.entries(report.threatBreakdown).map(([k, v]) => (
                    <div key={k} className="ww-stat-pill">{k.toUpperCase()} <b>{v}</b></div>
                  ))}
                </div>
                <div className="ww-card-list">
                  {report.watchlist.map((w) => (
                    <div key={w.id} className="ww-card">
                      <div className="ww-card-top"><span className="ww-card-name">{w.name}</span> <span className={`ww-pill ww-threat-${w.threat}`}>{w.threat}</span></div>
                      <div className="ww-card-body">{w.summary}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {activeView === 'dashboard' && (
          <div className="ww-view ww-section">
            <p className="ww-eyebrow">Dashboard</p>
            <h1>Desk status</h1>
            <div className="ww-dash-grid">
              <DashCard title="Conflict zones tracked" value={conflicts.length} status={config?.acled ? 'ACLED live feed' : 'Curated dataset'} on={!!config?.acled} />
              <DashCard title="Countries measured" value={countriesLoaded ? '~180 (full coverage)' : 'Loading…'} status="world-atlas, bundled at build time" on={countriesLoaded} />
              <DashCard title="Map tiles" value={config?.mapbox ? 'Mapbox (HD)' : 'Free (CARTO/Esri)'} status={config?.mapbox ? 'Mapbox token set' : 'No key required'} on />
              <DashCard title="AI Predictions" value={config?.anthropic ? 'Live' : 'Placeholder'} status={config?.anthropic ? 'ANTHROPIC_API_KEY set' : 'Add ANTHROPIC_API_KEY'} on={!!config?.anthropic} />
              <DashCard title="Global indicators" value="Live" status="World Bank + IMF DataMapper + UNHCR — no key required" on />
              <DashCard title="Power plants" value={powerPlants ? `${powerPlants.count} tracked` : 'Live'} status="Global Power Plant Database (WRI, CC BY 4.0) — no key required" on />
              <DashCard title="Mines / Ports / Smelters / Refineries / Dams" value="Live" status="Wikidata + OpenStreetMap + USGS MRDS — no key required, refreshed every 6h" on />
              <DashCard title="GDELT news monitor" value="Live" status="GDELT DOC 2.0 API, merged into Intel Feed — no key required" on />
              <DashCard title="Active fires" value={config?.firms ? 'Live' : 'Not connected'} status={config?.firms ? 'FIRMS_MAP_KEY set' : 'Needs free FIRMS_MAP_KEY'} on={!!config?.firms} />
              <DashCard title="Earthquakes" value="Live" status="USGS Earthquake Hazards Program — no key required" on />
              <DashCard title="Commodities" value={config?.fredCommodities ? 'Live' : 'Not connected'} status={config?.fredCommodities ? 'FRED_API_KEY set' : 'Needs free FRED_API_KEY'} on={!!config?.fredCommodities} />
              <DashCard title="Bloomberg live" value="Embedded on War Map" status="Bloomberg Originals — free public YouTube stream, no key required" on />
              <DashCard title="X" value={config?.xTwitter ? 'Live' : 'Not connected'} status={config?.xTwitter ? 'X_BEARER_TOKEN set' : 'Needs X_BEARER_TOKEN (paid API tier)'} on={!!config?.xTwitter} />
            </div>

            {commodities?.live && commodities.items?.length > 0 && (
              <>
                <p className="ww-eyebrow ww-spaced-lg">Commodities</p>
                <h2 className="ww-h2">Latest benchmark prices (FRED)</h2>
                <div className="ww-ticker-row">
                  {commodities.items.map((c) => (
                    <div key={c.id} className="ww-ticker-card">
                      <div className="ww-ticker-label">{c.label}</div>
                      <div className="ww-ticker-value">{c.value != null ? c.value.toLocaleString() : '—'} <span className="ww-muted-inline">{c.unit}</span></div>
                      <div className="ww-muted-inline">{c.date}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );

  function MiniFeed() {
    const [items, setItems] = useState([]);
    useEffect(() => {
      fetch('/api/whitewatch/news?limit=8').then((r) => r.json()).then((d) => setItems(d.items || [])).catch(() => setItems([]));
    }, []);
    if (items.length === 0) return <div className="ww-muted">No live items yet.</div>;
    return <div className="ww-feed-list">{items.map((item) => <FeedCard key={item.id || item.link} item={item} compact />)}</div>;
  }
}

function FeedCard({ item, compact }) {
  return (
    <a className={`ww-feed-item ww-threat-${item.threat} ${item.image && !compact ? 'ww-has-image' : ''}`} href={item.link} target="_blank" rel="noopener noreferrer">
      {item.image && !compact && (
        <img
          className="ww-feed-item-image"
          src={item.image}
          alt=""
          loading="lazy"
          onError={(e) => { e.currentTarget.style.display = 'none'; e.currentTarget.parentElement.classList.remove('ww-has-image'); }}
        />
      )}
      <div className="ww-feed-item-body">
        <div className="ww-feed-item-meta"><span>{item.source}</span><span>{item.region}</span><span>{timeAgo(item.publishedAt)}</span></div>
        <div className="ww-feed-item-title">{item.title}</div>
      </div>
    </a>
  );
}

function DashCard({ title, value, status, on }) {
  return (
    <div className="ww-dash-card">
      <div className="ww-dash-card-title">{title}</div>
      <div className="ww-dash-card-value">{value}</div>
      <div className={`ww-dash-card-status ${on ? 'ww-on' : 'ww-off'}`}>{on ? '●' : '○'} {status}</div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Scoped styles — everything lives under .ww-root so it can't leak into
// or collide with the rest of whitewater-management's styling. Built for
// a laptop/desktop viewport first (this is a trading-desk tool, not a
// mobile app) — it still functions on a phone, just tighter.
// ---------------------------------------------------------------------
const CSS = `
.ww-root {
  --ww-bg: #06090b; --ww-surface: #0c1116; --ww-surface2: #121924; --ww-border: #202b36;
  --ww-text: #dde5eb; --ww-text-dim: #8492a1; --ww-text-mute: #4d5a68;
  --ww-accent: #2dd4bf; --ww-critical: #ff3b3b; --ww-high: #ff9f1c; --ww-medium: #ffd93d; --ww-low: #4d9fff; --ww-stable: #22323f;
  --ww-asset-mine: #c084fc; --ww-asset-port: #38bdf8; --ww-asset-smelter: #fb923c; --ww-asset-refinery: #f472b6; --ww-asset-dam: #a3e635;
  --ww-asset-fire: #ff5a1f; --ww-asset-quake: #facc15;
  height: 100vh; display: flex; flex-direction: column; background: var(--ww-bg); color: var(--ww-text);
  font-family: system-ui, -apple-system, sans-serif; overflow: hidden;
  min-width: 320px;
}
.ww-root * { box-sizing: border-box; }
.ww-root button { font-family: inherit; }
.ww-desktop-notice { display: none; background: rgba(255,159,28,0.12); color: var(--ww-high); border-bottom: 1px solid var(--ww-border); font-size: 11px; padding: 6px 14px; text-align: center; }
@media (max-width: 860px) { .ww-desktop-notice { display: block; } }
.ww-topbar { display: flex; align-items: center; gap: 20px; padding: 10px 16px; background: var(--ww-surface); border-bottom: 1px solid var(--ww-border); flex-shrink: 0; }
.ww-brand { display: flex; align-items: center; gap: 7px; }
.ww-brand-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ww-critical); box-shadow: 0 0 8px var(--ww-critical); }
.ww-brand-name { font-weight: 800; letter-spacing: 1.5px; font-size: 15px; font-family: ui-monospace, monospace; }
.ww-back-link { font-family: ui-monospace, monospace; font-size: 10.5px; letter-spacing: 0.5px; color: var(--ww-text-mute); text-decoration: none; margin-right: 2px; }
.ww-back-link:hover { color: var(--ww-accent); }
.ww-tabs { display: flex; gap: 4px; flex: 1; overflow-x: auto; }
.ww-tab { background: transparent; border: 1px solid transparent; color: var(--ww-text-dim); font-family: ui-monospace, monospace; font-size: 12px; padding: 7px 12px; border-radius: 5px; cursor: pointer; white-space: nowrap; }
.ww-tab.ww-active { color: var(--ww-accent); background: rgba(45,212,191,0.12); border-color: var(--ww-border); }
.ww-topbar-right { display: flex; align-items: center; gap: 6px; font-family: ui-monospace, monospace; font-size: 11px; color: var(--ww-critical); font-weight: 700; }
.ww-live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ww-critical); }
.ww-clock { color: var(--ww-text-mute); font-weight: 500; margin-left: 8px; }
.ww-main { flex: 1; min-height: 0; }
.ww-view { display: flex; height: 100%; }
.ww-map-view { flex-direction: row; }
.ww-map-stage { position: relative; flex: 1; }
.ww-globe { position: absolute; inset: 0; }
.ww-map-loading { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; background: var(--ww-bg); font-family: ui-monospace, monospace; font-size: 12px; letter-spacing: 2px; color: var(--ww-text-dim); z-index: 20; }
.ww-spinner { width: 34px; height: 34px; border: 2px solid var(--ww-border); border-top-color: var(--ww-accent); border-radius: 50%; animation: ww-spin 0.9s linear infinite; }
@keyframes ww-spin { to { transform: rotate(360deg); } }
.ww-panel { position: absolute; background: rgba(12,17,22,0.92); border: 1px solid var(--ww-border); border-radius: 8px; padding: 14px; backdrop-filter: blur(6px); z-index: 10; }
.ww-panel-layers { top: 14px; left: 14px; width: 210px; }
.ww-panel-intel { top: 14px; right: 14px; width: 300px; }
.ww-panel-title { font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 1.5px; color: var(--ww-text-mute); text-transform: uppercase; margin-bottom: 8px; }
.ww-spaced { margin-top: 14px; }
.ww-chip-row { display: flex; flex-wrap: wrap; gap: 6px; }
.ww-chip { background: var(--ww-surface2); border: 1px solid var(--ww-border); color: var(--ww-text-dim); font-family: ui-monospace, monospace; font-size: 11px; padding: 5px 10px; border-radius: 20px; cursor: pointer; }
.ww-chip.ww-active { color: var(--ww-bg); background: var(--ww-accent); border-color: var(--ww-accent); font-weight: 700; }
.ww-chip.ww-threat-critical.ww-active { background: var(--ww-critical); border-color: var(--ww-critical); }
.ww-chip.ww-threat-high.ww-active { background: var(--ww-high); border-color: var(--ww-high); }
.ww-chip.ww-threat-medium.ww-active { background: var(--ww-medium); border-color: var(--ww-medium); }
.ww-chip.ww-threat-low.ww-active { background: var(--ww-low); border-color: var(--ww-low); }
.ww-toggle-row { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ww-text-dim); padding: 4px 0; cursor: pointer; }
.ww-close-btn { position: absolute; top: 8px; right: 10px; background: none; border: none; color: var(--ww-text-mute); font-size: 18px; cursor: pointer; }
.ww-zone-badge { display: inline-block; font-family: ui-monospace, monospace; font-size: 10px; font-weight: 700; letter-spacing: 1px; padding: 3px 8px; border-radius: 3px; text-transform: uppercase; margin-bottom: 8px; }
.ww-zone-badge.ww-threat-critical { background: rgba(255,59,59,0.15); color: var(--ww-critical); }
.ww-zone-badge.ww-threat-high { background: rgba(255,159,28,0.15); color: var(--ww-high); }
.ww-zone-badge.ww-threat-medium { background: rgba(255,217,61,0.15); color: var(--ww-medium); }
.ww-zone-badge.ww-threat-low { background: rgba(77,159,255,0.15); color: var(--ww-low); }
.ww-zone-badge.ww-threat-stable { background: rgba(125,150,170,0.15); color: var(--ww-text-dim); }
.ww-zone-badge.ww-asset-badge { background: rgba(45,212,191,0.15); color: var(--ww-accent); }
.ww-zone-name { margin: 0 0 2px; font-size: 18px; }
.ww-zone-region { font-size: 11px; color: var(--ww-text-mute); font-family: ui-monospace, monospace; }
.ww-zone-status { font-size: 12px; color: var(--ww-accent); margin: 6px 0; font-weight: 600; }
.ww-zone-summary { font-size: 13px; color: var(--ww-text-dim); line-height: 1.5; }
.ww-zone-actors { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
.ww-zone-actors span { font-size: 10px; font-family: ui-monospace, monospace; background: var(--ww-surface2); border: 1px solid var(--ww-border); padding: 3px 7px; border-radius: 4px; color: var(--ww-text-dim); }
.ww-asset-fields { display: flex; flex-direction: column; gap: 6px; margin: 10px 0; }
.ww-asset-field { display: flex; justify-content: space-between; align-items: baseline; font-size: 12px; border-bottom: 1px dashed var(--ww-border); padding-bottom: 4px; }
.ww-asset-field span { font-family: ui-monospace, monospace; font-size: 9.5px; letter-spacing: 0.6px; color: var(--ww-text-mute); }
.ww-asset-field b { color: var(--ww-text); font-weight: 600; }
.ww-asset-source { font-size: 10.5px; color: var(--ww-text-mute); margin-top: 10px; }
.ww-side-feed { width: 320px; flex-shrink: 0; overflow-y: auto; background: var(--ww-surface); border-right: 1px solid var(--ww-border); padding: 14px; }
.ww-feed-list { display: flex; flex-direction: column; gap: 10px; }
.ww-feed-item { border: 1px solid var(--ww-border); border-left: 3px solid var(--ww-text-mute); border-radius: 4px; padding: 10px; background: var(--ww-surface2); text-decoration: none; color: inherit; display: block; }
.ww-feed-item.ww-threat-critical { border-left-color: var(--ww-critical); }
.ww-feed-item.ww-threat-high { border-left-color: var(--ww-high); }
.ww-feed-item.ww-threat-medium { border-left-color: var(--ww-medium); }
.ww-feed-item.ww-threat-low { border-left-color: var(--ww-low); }
.ww-feed-item-meta { display: flex; justify-content: space-between; gap: 6px; font-family: ui-monospace, monospace; font-size: 9px; color: var(--ww-text-mute); margin-bottom: 5px; text-transform: uppercase; }
.ww-feed-item-meta span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ww-feed-item-title { font-size: 12.5px; line-height: 1.4; }
.ww-feed-item.ww-has-image { padding: 0; overflow: hidden; }
.ww-feed-item-image { display: block; width: 100%; height: 130px; object-fit: cover; background: var(--ww-surface2); border-bottom: 1px solid var(--ww-border); }
.ww-feed-item.ww-has-image .ww-feed-item-body { padding: 10px; }
.ww-section { flex-direction: column; padding: 20px 26px; overflow-y: auto; width: 100%; }
.ww-eyebrow { font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 1.5px; color: var(--ww-text-mute); text-transform: uppercase; margin: 0; }
.ww-section h1 { margin: 4px 0 12px; font-size: 21px; }
.ww-muted { color: var(--ww-text-mute); font-size: 12px; }
.ww-mini-caption { margin-top: 8px; font-size: 10.5px; line-height: 1.4; }
.ww-feed-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.ww-search { background: var(--ww-surface2); border: 1px solid var(--ww-border); color: var(--ww-text); padding: 9px 12px; border-radius: 6px; font-size: 13px; width: 240px; }
.ww-refresh-btn { margin-left: auto; background: var(--ww-surface2); border: 1px solid var(--ww-border); color: var(--ww-accent); font-family: ui-monospace, monospace; font-size: 11px; padding: 8px 14px; border-radius: 6px; cursor: pointer; }
.ww-feed-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.ww-spaced-sm { margin-top: 10px; margin-bottom: 4px; }
.ww-hero-card { display: block; position: relative; text-decoration: none; color: inherit; border: 1px solid var(--ww-border); border-radius: 6px; overflow: hidden; background: var(--ww-surface2); margin: 14px 0 18px; }
.ww-hero-image { display: block; width: 100%; height: 320px; object-fit: cover; background: var(--ww-surface2); }
.ww-hero-badge { position: absolute; top: 14px; left: 14px; font-family: ui-monospace, monospace; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; padding: 4px 10px; border-radius: 3px; text-transform: uppercase; background: rgba(0,0,0,0.55); backdrop-filter: blur(2px); }
.ww-hero-badge.ww-threat-critical { color: var(--ww-critical); }
.ww-hero-badge.ww-threat-high { color: var(--ww-high); }
.ww-hero-badge.ww-threat-medium { color: var(--ww-medium); }
.ww-hero-badge.ww-threat-low { color: var(--ww-low); }
.ww-hero-title { font-size: 20px; line-height: 1.3; margin: 14px 16px 6px; }
.ww-hero-meta { font-family: ui-monospace, monospace; font-size: 10.5px; color: var(--ww-text-mute); text-transform: uppercase; letter-spacing: 0.5px; margin: 0 16px 16px; }
.ww-card-list { display: flex; flex-direction: column; gap: 10px; }
.ww-card { background: var(--ww-surface); border: 1px solid var(--ww-border); border-radius: 8px; padding: 14px 16px; }
.ww-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 5px; }
.ww-card-name { font-weight: 700; font-size: 13.5px; }
.ww-card-body { font-size: 12.5px; color: var(--ww-text-dim); line-height: 1.5; white-space: pre-wrap; }
.ww-pill { font-family: ui-monospace, monospace; font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 20px; text-transform: uppercase; background: var(--ww-surface2); color: var(--ww-text-dim); border: 1px solid var(--ww-border); }
.ww-pill.ww-threat-critical { background: rgba(255,59,59,0.15); color: var(--ww-critical); }
.ww-pill.ww-threat-high { background: rgba(255,159,28,0.15); color: var(--ww-high); }
.ww-pill.ww-threat-medium { background: rgba(255,217,61,0.15); color: var(--ww-medium); }
.ww-pill.ww-threat-low { background: rgba(77,159,255,0.15); color: var(--ww-low); }
.ww-stat-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
.ww-stat-pill { font-family: ui-monospace, monospace; font-size: 11px; padding: 8px 12px; border-radius: 6px; background: var(--ww-surface); border: 1px solid var(--ww-border); }
.ww-dash-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.ww-dash-card { background: var(--ww-surface); border: 1px solid var(--ww-border); border-radius: 8px; padding: 16px; }
.ww-dash-card-title { font-family: ui-monospace, monospace; font-size: 11px; color: var(--ww-text-mute); text-transform: uppercase; margin-bottom: 8px; }
.ww-dash-card-value { font-size: 20px; font-weight: 700; }
.ww-dash-card-status { font-size: 11px; margin-top: 6px; font-family: ui-monospace, monospace; }
.ww-dash-card-status.ww-on { color: var(--ww-accent); }
.ww-dash-card-status.ww-off { color: var(--ww-text-mute); }
.ww-ticker-row { display: flex; flex-wrap: wrap; gap: 12px; }
.ww-ticker-card { background: var(--ww-surface); border: 1px solid var(--ww-border); border-radius: 8px; padding: 14px 18px; min-width: 150px; }
.ww-ticker-label { font-family: ui-monospace, monospace; font-size: 10.5px; color: var(--ww-text-mute); text-transform: uppercase; margin-bottom: 6px; }
.ww-ticker-value { font-size: 18px; font-weight: 700; }
.ww-zone-marker { width: 16px; height: 16px; border-radius: 50%; border: 2px solid rgba(255,255,255,0.13); cursor: pointer; box-shadow: 0 0 10px currentColor; }
.ww-zone-marker.ww-threat-critical { background: var(--ww-critical); color: var(--ww-critical); }
.ww-zone-marker.ww-threat-high { background: var(--ww-high); color: var(--ww-high); }
.ww-zone-marker.ww-threat-medium { background: var(--ww-medium); color: var(--ww-medium); }
.ww-zone-marker.ww-threat-low { background: var(--ww-low); color: var(--ww-low); }
.ww-asset-marker { width: 11px; height: 11px; cursor: pointer; transform: rotate(45deg); border: 1.5px solid rgba(255,255,255,0.35); box-shadow: 0 0 6px currentColor; }
.ww-asset-marker.ww-asset-power { background: var(--ww-accent); color: var(--ww-accent); }
.ww-asset-marker.ww-asset-mine { background: var(--ww-asset-mine); color: var(--ww-asset-mine); }
.ww-asset-marker.ww-asset-port { background: var(--ww-asset-port); color: var(--ww-asset-port); }
.ww-asset-marker.ww-asset-smelter { background: var(--ww-asset-smelter); color: var(--ww-asset-smelter); }
.ww-asset-marker.ww-asset-refinery { background: var(--ww-asset-refinery); color: var(--ww-asset-refinery); }
.ww-asset-marker.ww-asset-dam { background: var(--ww-asset-dam); color: var(--ww-asset-dam); }
.ww-asset-marker.ww-asset-fire { background: var(--ww-asset-fire); color: var(--ww-asset-fire); }
.ww-asset-marker.ww-asset-quake { background: var(--ww-asset-quake); color: var(--ww-asset-quake); }
.ww-asset-swatch { display: inline-block; width: 8px; height: 8px; border-radius: 2px; transform: rotate(45deg); margin: 0 3px; vertical-align: middle; }
.ww-asset-swatch.ww-asset-mine { background: var(--ww-asset-mine); }
.ww-asset-swatch.ww-asset-port { background: var(--ww-asset-port); }
.ww-asset-swatch.ww-asset-smelter { background: var(--ww-asset-smelter); }
.ww-asset-swatch.ww-asset-refinery { background: var(--ww-asset-refinery); }
.ww-asset-swatch.ww-asset-dam { background: var(--ww-asset-dam); }
.ww-asset-swatch.ww-asset-fire { background: var(--ww-asset-fire); }
.ww-asset-swatch.ww-asset-quake { background: var(--ww-asset-quake); }
.ww-pill.ww-asset-pill.ww-asset-mine { background: rgba(192,132,252,0.15); color: var(--ww-asset-mine); }
.ww-pill.ww-asset-pill.ww-asset-port { background: rgba(56,189,248,0.15); color: var(--ww-asset-port); }
.ww-pill.ww-asset-pill.ww-asset-smelter { background: rgba(251,146,60,0.15); color: var(--ww-asset-smelter); }
.ww-pill.ww-asset-pill.ww-asset-refinery { background: rgba(244,114,182,0.15); color: var(--ww-asset-refinery); }
.ww-pill.ww-asset-pill.ww-asset-dam { background: rgba(163,230,53,0.15); color: var(--ww-asset-dam); }
.ww-root .maplibregl-popup-content { background: var(--ww-surface) !important; color: var(--ww-text) !important; border: 1px solid var(--ww-border) !important; }
.ww-spaced-lg { margin-top: 30px; }
.ww-h2 { font-size: 15px; margin: 2px 0 12px; }
.ww-muted-inline { color: var(--ww-text-mute); font-size: 10.5px; margin-left: 3px; }
.ww-table-wrap { overflow-x: auto; border: 1px solid var(--ww-border); border-radius: 8px; }
.ww-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.ww-table th, .ww-table td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--ww-border); white-space: nowrap; }
.ww-table th { font-family: ui-monospace, monospace; font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: var(--ww-text-mute); background: var(--ww-surface2); }
.ww-table tbody tr:hover { background: var(--ww-surface2); }
.ww-table td.ww-neg { color: var(--ww-critical); font-weight: 600; }
.ww-live-embed-wrap { position: relative; width: 100%; max-width: 900px; aspect-ratio: 16 / 9; border-radius: 8px; overflow: hidden; border: 1px solid var(--ww-border); background: #000; }
.ww-live-embed-wrap-mini { max-width: none; }
.ww-live-embed { width: 100%; height: 100%; border: 0; }
.ww-card-link { text-decoration: none; color: inherit; display: block; cursor: pointer; }
`;
