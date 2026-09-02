# Models — how to add one of your algorithms

This is the plug-in surface for the desk's models. The rest of the app never
talks to a specific model — only to the interfaces here — so you can build and
swap algos without touching any UI or routes.

## The layout

```
models/
  types.ts        # shared types + the three model interfaces (the contracts)
  shared.ts       # optional helpers (aiEnabled(), seeded rng, …)
  registry.ts     # THE HUB — every model is imported and wired in here
  impl/
    macro-tracker.ts   # a MacroModel      (demo — replace body with your model)
    distresse.ts       # an EvaluatorModel (demo)
    intra-exitus.ts    # a LevelsModel     (demo)
    _template.ts       # copy this to add a new model
```

> The three files in `impl/` currently hold **demo logic** so the UI works. Each
> has a clearly-marked `DEMO BODY` — replace it with your real model. The
> input/output shapes stay the same.

## Pick your interface

Each model implements exactly one contract (see `types.ts`):

| Interface        | Method                          | Returns          | Example                |
| ---------------- | ------------------------------- | ---------------- | ---------------------- |
| `EvaluatorModel` | `evaluate(idea)`                | `StressVerdict`  | Distresse              |
| `LevelsModel`    | `plan(idea)`                    | `EntryExitPlan`  | Intra / Exitus         |
| `MacroModel`     | `read(dateISO)`                 | `MacroReading`   | Sentimentum · Macro    |
| `EquityModel`    | `read(dateISO)`                 | `EquityReading`  | Sentimentum · Equity   |

Need a shape these don't cover? Add a new interface to `types.ts` and a matching
roster in `registry.ts` — same pattern.

## Add a model in 3 steps

1. **Build it.** Copy `impl/_template.ts` to `impl/<your-model>.ts`, set `meta`,
   implement the one method, return the typed shape. Branch on `aiEnabled()` if
   you want an LLM path.
2. **Register it.** In `registry.ts`: import it, add it to `models`, and to the
   matching array (`macroModels` / `evaluators` / `levelsModels`) if it's live.
3. **Done.** It shows up on `/models`; wire it to a screen if it needs its own.

## Isolation — models can't interfere with each other

Each model is a **separate file** in `impl/` that implements its interface and
holds **no shared mutable state**. Building or breaking one can't affect another.
The *only* shared file is `registry.ts`, and only by a one-line entry per model —
so the surface where two models could ever collide is a single array push.

If you build several at once, keep each on its own git branch (or worktree) and
merge when green; the only merge point is that one `registry.ts` line.

## Turning on real AI

Set `AI_GATEWAY_API_KEY` (Vercel AI Gateway) or `ANTHROPIC_API_KEY`. Then inside
a model, `if (aiEnabled())` call the AI SDK's `generateObject()` with a Zod
schema mirroring the return type, model string e.g. `"anthropic/claude-sonnet-4.5"`.
