import { ModuleNav } from "@/components/ModuleNav";
import { Card, Badge } from "@/components/ui";
import { proposals, members } from "@/lib/sample-data";
import { usd } from "@/lib/format";
import type { Proposal } from "@/lib/types";

// PROPOSALS — trade ideas + voting. Shared capital means shared decisions.
// The vote buttons are wired to a server action stub; hook them to your DB
// to make them persist.
export default function ProposalsPage() {
  const quorum = Math.ceil(members.length / 2) + 0; // simple majority target

  return (
    <div>
      <ModuleNav crumb="Proposals" />
      <main className="mx-auto max-w-5xl px-5 py-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Trade proposals</h1>
            <p className="mt-1 text-sm text-foreground/60">
              Pitch an idea, log the thesis, and vote. Needs {quorum} of{" "}
              {members.length} yes votes to approve.
            </p>
          </div>
          <button className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background">
            New proposal
          </button>
        </div>

        <div className="mt-6 space-y-4">
          {proposals.map((p) => (
            <ProposalCard key={p.id} p={p} total={members.length} quorum={quorum} />
          ))}
        </div>
      </main>
    </div>
  );
}

function ProposalCard({
  p,
  total,
  quorum,
}: {
  p: Proposal;
  total: number;
  quorum: number;
}) {
  const yes = p.votes.filter((v) => v.value === "yes").length;
  const no = p.votes.filter((v) => v.value === "no").length;
  const proposer = members.find((m) => m.id === p.proposedBy)?.name ?? "—";
  const met = yes >= quorum;

  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Badge tone={p.side === "buy" ? "up" : "down"}>
              {p.side.toUpperCase()}
            </Badge>
            <span className="text-lg font-semibold">{p.symbol}</span>
            <span className="text-sm text-foreground/50">
              target {usd(p.targetUsd)}
            </span>
          </div>
          <p className="mt-2 max-w-2xl text-sm text-foreground/80">{p.thesis}</p>
          <p className="mt-2 text-xs text-foreground/40">
            Proposed by {proposer}
          </p>
        </div>
        <Badge tone={met ? "up" : "warn"}>
          {yes}/{total} yes
        </Badge>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button className="rounded-md bg-emerald-500/15 px-3 py-1.5 text-sm font-medium text-emerald-500 hover:bg-emerald-500/25">
          Vote yes
        </button>
        <button className="rounded-md bg-rose-500/15 px-3 py-1.5 text-sm font-medium text-rose-500 hover:bg-rose-500/25">
          Vote no
        </button>
        <span className="text-xs text-foreground/40">
          {yes} yes · {no} no · {total - yes - no} not voted
        </span>
      </div>
    </Card>
  );
}
