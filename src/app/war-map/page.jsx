import DynamicWarMap from './DynamicWarMap';

// The actual dynamic(..., { ssr: false }) import lives in DynamicWarMap.jsx
// now, not here — see that file's comment for why. This stays a plain
// Server Component so `metadata` below still works the normal Next.js way.
export const metadata = {
  title: 'War Map — Whitewater',
  description: 'Live conflict-zone monitoring, threat tiers, and intel feed.',
};

export default function WarMapPage() {
  return <DynamicWarMap />;
}
