// ---------------------------------------------------------------------------
// The "models" layer. Every model — Distresse, Intra, the Macro Tracker, and
// your own proprietary macro algos — is described by ModelMeta and plugged into
// the registry. Nothing sits under one monolith; the registry is the hub.
// ---------------------------------------------------------------------------

export type ModelKind = "evaluator" | "levels" | "macro" | "equity" | "custom";

export type ModelStatus = "live" | "beta" | "planned";

export type ModelMeta = {
  id: string;
  name: string; // e.g. "Distresse"
  kind: ModelKind;
  status: ModelStatus;
  tagline: string; // one line for the hub card
  description: string; // what it does + how to read it
  etymology?: string; // the naming story, shown small
};

// --- A trade idea, the input to the Stress Test engines --------------------

export type Instrument = "long" | "short" | "call" | "put" | "future";

// What "long"/"short" alone doesn't tell you: over what window this idea is
// meant to play out. "Long AAPL" is a different bet depending on whether it's
// a same-day read, a multi-week swing into a known date, a multi-month
// position, or a multi-year hold — the SAME instrument field, four different
// theses. This is deliberately a small, closed set (not free text) so models
// can key real behavior off it (see distresse.ts's DIMENSION_RELEVANCE).
//   intraday   — hours; closed same day or next session
//   swing      — days to a few weeks; often built around a known date/event
//   position   — weeks to a few months (the implicit default before this field existed)
//   long-term  — 6+ months, thesis expected to take quarters to play out
export type IdeaTimeframe = "intraday" | "swing" | "position" | "long-term";

// What's actually expected to move the name, if anything specific — distinct
// from `IdeaTimeframe` (you can hold an earnings bet for a swing OR just the
// print itself). "earnings" is the concrete case the platform gets asked
// about most ("long AAPL just for earnings, betting on the print"): it says
// this is a bet on ONE dated event, not the multi-quarter fundamental case —
// which should lean on News/positioning going into the print, not on
// valuation or the macro regime. `general-thesis` (the default) preserves the
// original undifferentiated behavior.
export type IdeaCatalystType =
  | "general-thesis"
  | "earnings"
  | "fed-macro-event"
  | "product-launch"
  | "technical-level";

// Evidence that can ride along with an idea — e.g. the Incepta equity engine's
// risk/quality/valuation read for the ticker. Distresse is the judge; this is
// the evidence it judges on. Loosely typed so any evidence source can attach.
export type TradeEvidence = {
  source: string; // e.g. "Incepta v1.0.0"
  confidence: string; // the security's confidence level
  asOf?: string;
  risk?: Record<string, number | null> | null;
  quality?: Record<string, number | null> | null;
  valuation?: Record<string, number | null> | null;
  flags?: string[];
};

export type TradeIdea = {
  ticker: string;
  instrument: Instrument;
  thesis: string;
  timeframe?: IdeaTimeframe; // defaults to "position" wherever read — see distresse.ts
  catalystType?: IdeaCatalystType; // defaults to "general-thesis" wherever read
  horizon?: string; // legacy free-text display horizon, e.g. "3–6 months" — kept for existing callers, independent of `timeframe`
  sizePct?: number; // intended % of book
  evidence?: TradeEvidence; // optional engine evidence for Distresse
};

// --- Distresse output: the adversarial verdict -----------------------------

export type Rating = "go" | "conditional" | "no-go";

export type Dimension = {
  label: string; // "Macro regime fit"
  score: number; // -100 (hostile) .. +100 (supportive). Meaningless when available === false — see below.
  note: string;
  // false when the real source behind this dimension had nothing usable for
  // this idea (not covered, insufficient confidence, unreachable, no signal
  // transactions, etc.) — `score` is then a neutral placeholder (0), NEVER a
  // fabricated read, and `note` explains why. UI must render an abstain
  // state, not a score bar, when this is false (see ModelPanels.tsx).
  available: boolean;
};

export type StressVerdict = {
  ticker: string;
  instrument: Instrument;
  rating: Rating;
  conviction: number; // 0..100
  regime: string; // one-line macro regime read
  dimensions: Dimension[]; // quant/macro eagle-eye scorecard
  devilsAdvocate: string[]; // the strongest case against
  tailRisks: string[]; // low-probability, high-impact
  bottomLine: string; // straight-up call, in plain words
  generatedBy: string; // "Distresse (sample)" or model id
};

// --- Intra output: entry/exit plan -----------------------------------------

export type EntryExitPlan = {
  ticker: string;
  instrument: Instrument;
  bias: "long" | "short";
  entryZone: [number, number]; // buy/sell band
  stop: number;
  targets: number[]; // scale-out levels
  sizingPct: number; // suggested % of book
  timeStop: string; // "exit if thesis hasn't played by …"
  rationale: string;
  invalidations: string[]; // what kills the setup
  generatedBy: string;
};

// --- Macro Tracker output: a dated reading ---------------------------------

export type SectorRead = {
  sector: string;
  sentiment: number; // -100 .. +100
  note: string;
};

export type Catalyst = {
  date: string; // ISO
  event: string;
  importance: "high" | "medium" | "low";
};

export type MacroReading = {
  date: string; // ISO date of the reading
  regime: string; // e.g. "Late-cycle, easing bias"
  sentiment: number; // overall -100 .. +100
  sectors: SectorRead[];
  catalysts: Catalyst[];
  summary: string; // background / narrative
  generatedBy: string;
};

// --- Equity model output: a bottom-up read --------------------------------
// The equity counterpart to MacroReading. Adjust the fields to whatever your
// equity model actually produces — this is a sensible starting shape.

export type EquitySignal = {
  symbol: string;
  score: number; // -100 (bearish) .. +100 (bullish)
  note: string;
};

export type EquityReading = {
  date: string; // ISO date of the reading
  breadth: number; // overall equity-market read, -100 .. +100
  signals: EquitySignal[]; // per-name (or per-theme) reads
  summary: string; // background / narrative
  generatedBy: string;
};

// ---------------------------------------------------------------------------
// Model contracts.
//
// Every algorithm you build implements ONE of these interfaces and gets
// registered in registry.ts. That's the whole plug-in surface — pick the kind
// that matches what your model produces, implement the single method, register
// it. The app only ever talks to these interfaces, never to a specific model.
// ---------------------------------------------------------------------------

export interface BaseModel {
  meta: ModelMeta;
}

// Judges a trade idea (Distresse and anything like it).
export interface EvaluatorModel extends BaseModel {
  evaluate(idea: TradeIdea): Promise<StressVerdict>;
}

// Turns an idea into entry/exit levels (Intra / Exitus).
export interface LevelsModel extends BaseModel {
  plan(idea: TradeIdea): Promise<EntryExitPlan>;
}

// Produces a dated macro reading (Sentimentum · Macro + your macro algos).
export interface MacroModel extends BaseModel {
  read(dateISO: string): Promise<MacroReading>;
}

// Produces a dated equity reading (Sentimentum · Equity + your equity algos).
export interface EquityModel extends BaseModel {
  read(dateISO: string): Promise<EquityReading>;
}

export type AnyModel =
  | EvaluatorModel
  | LevelsModel
  | MacroModel
  | EquityModel;
