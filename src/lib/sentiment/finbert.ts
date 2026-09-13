import "server-only";
import type { HeadlineSentiment, SentimentLabel } from "./types";

// ═══════════════════════════════════════════════════════════════════════════
// WW-SENTIMENT — the real model client.
//
// Model: ProsusAI/finbert — a BERT model fine-tuned on the Financial
// PhraseBank for exactly this task (financial-news sentiment, three classes:
// positive / negative / neutral). Not a generic sentiment model repurposed
// for finance; it is the standard, widely-cited finance-tuned choice this
// task asked to verify.
//
// VERIFIED, AS OF 2026-09-13, VIA WebSearch/WebFetch (this sandbox has no
// outbound network access to actually call the endpoint — see below):
//
//   - Hugging Face's old "serverless Inference API" (the thing most 2023-24
//     tutorials describe, hosted at api-inference.huggingface.co and free
//     for any signed-in user) has been folded into "Inference Providers"
//     (huggingface.co/docs/inference-providers). Chat/LLM/image/video/
//     embedding tasks are now routed through third-party partner
//     infrastructure (DeepInfra, Together, Groq, ...) via
//     router.huggingface.co, and that marketplace layer does NOT list
//     text-classification among its supported tasks.
//   - Small CPU-hosted models — explicitly including text-classification —
//     are still served by Hugging Face's OWN infrastructure under the
//     "hf-inference" provider (huggingface.co/docs/inference-providers/
//     pricing: "hf-inference focuses mostly on CPU inference: text
//     embeddings, text ranking, text classification, smaller LLMs"). This is
//     the same infrastructure the old serverless API ran on, now billed
//     through the Inference Providers metering.
//   - Hugging Face's own docs page for the text-classification task
//     (huggingface.co/docs/inference-providers/tasks/text-classification)
//     names ProsusAI/finbert BY NAME as its recommended example: "A
//     sentiment analysis model specialized in financial sentiment." — this
//     is not a repurposed generic model, it is the documented intended use.
//   - EVERY Hugging Face account — including a brand-new free one, no
//     payment method required to sign up — receives a small monthly
//     inference credit ($0.10/month as of this research; HF's own docs flag
//     that figure as "subject to change") that is spent, at each provider's
//     own metered rate, on any Inference Providers call INCLUDING
//     hf-inference. There is no separate "free forever, unlimited" tier
//     left for this — it is a small prepaid allowance, not a permanent free
//     API. A small CPU BERT-classification call is cheap (compute-time
//     billed; a single-sentence classification on a ~440MB BERT model is
//     sub-second CPU work), so $0.10/month plausibly covers on the order of
//     hundreds to low thousands of headline scores for a small member
//     platform — but this codebase makes no specific claim about exactly
//     how many, because that was not independently measured from here.
//   - Exhausting the free credit fails CLEANLY (HTTP 402 Payment Required,
//     confirmed via Hugging Face's own community forum), not an auto-charge
//     — matching this codebase's existing "gate cleanly on a real key,
//     never guess past a limit" convention (see predictions/route.js's
//     ANTHROPIC_API_KEY check).
//   - The concrete REST contract multiple independent, current sources
//     converge on: `POST https://api-inference.huggingface.co/models/
//     ProsusAI/finbert`, header `Authorization: Bearer <token>`, body
//     `{"inputs": "<headline text>"}`, response a JSON array of
//     `[{label, score}, ...]` for the three classes (FinBERT's own labels
//     are lowercase: "positive" / "negative" / "neutral").
//
// WHAT THIS CODEBASE COULD NOT VERIFY (say so plainly, per this task's own
// rule): the exact endpoint above has NOT been called live from this
// sandbox — there is no outbound network access here at all (confirmed: a
// plain `curl` to api-inference.huggingface.co, router.huggingface.co, and
// even a plain https://example.com from this container's shell all fail at
// the network layer before reaching any real host). This module is built
// against the documented, cross-source-confirmed request/response schema
// above, exercised in this repo only against realistic MOCKED responses
// (see scripts/verify-sentiment.mjs) — never against the real API. The
// FIRST real call this code makes, once HF_API_KEY is set on a machine with
// real internet access, is the first true end-to-end confirmation of this
// integration, exactly the same "the next real run is the first true
// verification" situation graph-engine/README.md and weekly-engine/README.md
// already document for their own live-data paths.
//
// A KNOWN HISTORICAL BEHAVIOR OF THIS SAME UNDERLYING INFRASTRUCTURE, not
// independently re-confirmed here: a model that hasn't been called recently
// can return HTTP 503 with an `estimated_time` while it "warms up" on the
// provider's hardware. `wait_for_model` (see the request body below) is the
// long-standing, documented way to have the API hold the request open and
// retry server-side instead of surfacing that as an error — included
// because it costs nothing to send and, if it still behaves the way it has
// for years, turns a cold start into a slower success instead of a spurious
// failure. If this is wrong today, `callFinbert`'s existing timeout/error
// handling below still degrades honestly (see route.ts's fallback path).
// ═══════════════════════════════════════════════════════════════════════════

const FINBERT_MODEL = "ProsusAI/finbert";
const FINBERT_URL = `https://api-inference.huggingface.co/models/${FINBERT_MODEL}`;
const REQUEST_TIMEOUT_MS = 15000;

// Raw shape of one FinBERT class score, per the model card / documented
// text-classification response — see the verification notes above.
type FinbertClassScore = { label: string; score: number };

function isFinbertLabel(label: string): label is Exclude<SentimentLabel, "unavailable"> {
  return label === "positive" || label === "negative" || label === "neutral";
}

// Turns FinBERT's raw per-class array into this codebase's HeadlineSentiment
// shape by taking the argmax class as the winning label/score. FinBERT's
// three scores are a softmax distribution (sum to ~1), so the argmax is
// exactly "which of the three classes the model is most confident in."
function parseFinbertResponse(raw: unknown): HeadlineSentiment | null {
  // The API can return either `[{label,score}, ...]` (single input) or
  // `[[{label,score}, ...]]` (batched) depending on how the request was
  // shaped — this module always sends one string, but defends against both
  // documented shapes rather than assuming the flatter one.
  const arr = Array.isArray(raw) && Array.isArray(raw[0]) ? (raw[0] as FinbertClassScore[]) : (raw as FinbertClassScore[]);
  if (!Array.isArray(arr) || arr.length === 0) return null;

  let best: FinbertClassScore | null = null;
  for (const c of arr) {
    if (!c || typeof c.label !== "string" || typeof c.score !== "number") continue;
    if (!best || c.score > best.score) best = c;
  }
  if (!best || !isFinbertLabel(best.label)) return null;

  return { label: best.label, score: best.score, method: "finbert" };
}

export type FinbertCallResult =
  | { ok: true; sentiment: HeadlineSentiment }
  | { ok: false; reason: string }; // human-readable, shown verbatim in a headline's sentiment.note on fallback

// One real call, one headline. Never throws — every failure path returns
// `{ ok: false, reason }` so route.ts can decide (fallback vs abstain)
// without a try/catch at every call site.
export async function callFinbert(text: string): Promise<FinbertCallResult> {
  const apiKey = process.env.HF_API_KEY;
  if (!apiKey) {
    return { ok: false, reason: "HF_API_KEY is not set." };
  }

  let resp: Response;
  try {
    resp = await fetch(FINBERT_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ inputs: text, options: { wait_for_model: true } }),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (err) {
    return { ok: false, reason: `Network error calling the Hugging Face Inference API: ${(err as Error).message}` };
  }

  if (resp.status === 401 || resp.status === 403) {
    return { ok: false, reason: `Hugging Face rejected HF_API_KEY (HTTP ${resp.status}) — check the token's permissions.` };
  }
  if (resp.status === 402) {
    return { ok: false, reason: "Hugging Face free monthly inference credit is exhausted (HTTP 402 Payment Required)." };
  }
  if (resp.status === 429) {
    return { ok: false, reason: "Hugging Face Inference API rate limit hit (HTTP 429)." };
  }
  if (resp.status === 503) {
    return { ok: false, reason: "FinBERT is loading on Hugging Face's infrastructure (HTTP 503) — try again shortly." };
  }
  if (!resp.ok) {
    return { ok: false, reason: `Hugging Face Inference API error (HTTP ${resp.status}).` };
  }

  let json: unknown;
  try {
    json = await resp.json();
  } catch {
    return { ok: false, reason: "Could not parse the Hugging Face Inference API response as JSON." };
  }

  const sentiment = parseFinbertResponse(json);
  if (!sentiment) {
    return { ok: false, reason: "Hugging Face Inference API returned an unexpected response shape." };
  }
  return { ok: true, sentiment };
}

export function finbertConfigured(): boolean {
  return Boolean(process.env.HF_API_KEY);
}
