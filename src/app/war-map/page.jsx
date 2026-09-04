import dynamic from 'next/dynamic';

// MapLibre GL touches `window`/`document` at import time, so it can only run
// client-side. This server component just picks the client bundle with SSR
// turned off — Next.js will render a blank shell on first paint, then
// hydrate WarMapClient in the browser.
const WarMapClient = dynamic(() => import('./WarMapClient'), { ssr: false });

export const metadata = {
  title: 'War Map — Whitewater',
  description: 'Live conflict-zone monitoring, threat tiers, and intel feed.',
};

export default function WarMapPage() {
  return <WarMapClient />;
}
