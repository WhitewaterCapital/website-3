import { Badge, Card } from "@/components/ui";
import type {
  IntraExitusExport,
  IntraExitusPlan,
  PlanConfidence,
} from "@/lib/models/intra-exitus-export";

const dash = "—";
const px = (n: number | null | undefined) => (n == null ? dash : `$${n.toFixed(2)}`);
const confTone: Record<PlanConfidence, "up" | "warn" | "neutral"> = {
  actionable: "up",
  watch: "warn",
  insufficient: "neutral",
};

// Renders the REAL Intra/Exitus engine output. Actionable/watch plans show
// levels; abstains show the honest "standing aside" rationale — never a fake band.
export function IntraExitusReader({ data }: { data: IntraExitusExport }) {
  const actionable = data.plans.filter((p) => p.confidence !== "insufficient");

  return (
    <div className="space-y-8">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Entry / exit research</Badge>
          <span className="text-xs text-muted">
            Decision-support levels, not orders — the engine abstains when there&apos;s no clean setup
          </span>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">{data.disclaimer}</p>
        <p className="mt-2 font-mono text-[11px] text-muted">
          Intra/Exitus {data.schema_version} · engine {data.engine_version} · as of{" "}
          {data.as_of} · {actionable.length}/{data.plans.length} with a setup
        </p>
      </div>

      <div className="space-y-4">
        {data.plans.map((p) => (
          <PlanCard key={p.ticker} p={p} />
        ))}
      </div>
    </div>
  );
}

function PlanCard({ p }: { p: IntraExitusPlan }) {
  const abstain = p.confidence === "insufficient";
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-semibold">{p.ticker}</h3>
          <span className="text-sm text-muted tabular-nums">{px(p.lastClose)}</span>
          {!abstain && (
            <Badge tone={p.bias === "short" ? "down" : "up"}>{p.bias}</Badge>
          )}
        </div>
        <Badge tone={confTone[p.confidence]}>{p.confidence}</Badge>
      </div>

      {abstain ? (
        <p className="mt-3 text-sm text-muted">{p.rationale}</p>
      ) : (
        <>
          <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Field label="Entry zone" value={p.entryZone ? `${p.entryZone[0]} – ${p.entryZone[1]}` : dash} />
            <Field label="Stop" value={px(p.stop)} tone="down" />
            <Field label="Targets" value={p.targets.length ? p.targets.join("  ·  ") : dash} tone="up" />
            <Field label="Expected R" value={p.expectedR == null ? dash : p.expectedR.toFixed(2)} />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-2">
            <Field label="Size" value={p.sizingPct == null ? dash : `${p.sizingPct}% of book`} />
            <Field label="Time-stop" value={p.timeStop} />
          </div>
          <p className="mt-4 text-sm text-foreground/80">{p.rationale}</p>
          {p.invalidations.length > 0 && (
            <ul className="mt-3 space-y-1">
              {p.invalidations.map((inv, i) => (
                <li key={i} className="text-xs text-muted">— {inv}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}

function Field({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div
        className={`mt-1 text-sm font-semibold tabular-nums ${
          tone === "up" ? "text-emerald-500" : tone === "down" ? "text-rose-500" : ""
        }`}
      >
        {value}
      </div>
    </div>
  );
}
