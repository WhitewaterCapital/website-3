// ---------------------------------------------------------------------------
// Helpers shared by model implementations. Import what you need when you build
// a real model; none of this is required — it's just convenience.
// ---------------------------------------------------------------------------

// Is a real LLM available? Set AI_GATEWAY_API_KEY (Vercel AI Gateway) or
// ANTHROPIC_API_KEY to turn one on. Your model can branch on this to call an
// LLM when present and fall back to a heuristic when not.
export function aiEnabled(): boolean {
  return Boolean(process.env.AI_GATEWAY_API_KEY || process.env.ANTHROPIC_API_KEY);
}

// Deterministic PRNG seeded from a string — same input, same output. Handy for
// stable demo data; real models won't need it.
export function seeded(str: string) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  let a = h >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const pick = <T,>(rng: () => number, arr: T[]): T =>
  arr[Math.floor(rng() * arr.length)];

export const round = (n: number) => Math.round(n * 100) / 100;
