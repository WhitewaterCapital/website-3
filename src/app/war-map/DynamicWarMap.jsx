'use client';

import dynamic from 'next/dynamic';

// This file exists purely because of a real build error: this version of
// Next.js (16.2.12) refuses a dynamic(..., { ssr: false }) call made
// directly inside a Server Component ("`ssr: false` is not allowed with
// `next/dynamic` in Server Components"). page.jsx has no 'use client' at
// the top, so it's a Server Component, and it used to call dynamic() with
// ssr:false right there. Moving that exact same call one file down into an
// explicit Client Component satisfies the new rule with zero behavior
// change — page.jsx still renders a plain server shell first, and this
// file still defers WarMapClient's actual mount to the browser only,
// since MapLibre GL touches `window`/`document` at import time.
const WarMapClient = dynamic(() => import('./WarMapClient'), { ssr: false });

export default function DynamicWarMap() {
  return <WarMapClient />;
}
