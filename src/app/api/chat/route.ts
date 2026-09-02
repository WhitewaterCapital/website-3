import { NextResponse } from "next/server";
import { primaryMacro } from "@/lib/models/registry";
import { aiEnabled } from "@/lib/models/shared";

// ---------------------------------------------------------------------------
// Consensus chat.
//
// The bot answers with the current macro reading as context, so the 5 partners
// can talk toward a shared view. Right now it gives a grounded, deterministic
// response built from the day's reading. To make it conversational, wire the
// AI SDK's streamText() here with the reading + chat history as context
// (see the seam note in engine.ts).
// ---------------------------------------------------------------------------

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const message = String(body.message ?? "").trim();
  const today = new Date().toISOString().slice(0, 10);
  const reading = await primaryMacro().read(today);

  if (aiEnabled()) {
    // TODO: streamText({ model: "anthropic/claude-sonnet-4.5", system: ...reading, messages })
  }

  const top = [...reading.sectors].sort((a, b) => b.sentiment - a.sentiment)[0];
  const bottom = [...reading.sectors].sort((a, b) => a.sentiment - b.sentiment)[0];
  const next = reading.catalysts[0];

  const reply =
    `On today's read the regime is "${reading.regime}" with overall sentiment ` +
    `${reading.sentiment > 0 ? "+" : ""}${reading.sentiment}. ` +
    `Strongest cross-sector signal is ${top.sector} (${top.sentiment > 0 ? "+" : ""}${top.sentiment}), ` +
    `weakest is ${bottom.sector} (${bottom.sentiment}). ` +
    `Nearest catalyst: ${next.event} on ${next.date}. ` +
    (message
      ? `On "${message}" — my consensus lean is to weight the catalyst path over the current tape; ` +
        `if the desk disagrees, the crux is whether ${top.sector} leadership holds through ${next.event}.`
      : `Ask me where the desk should lean and I'll frame the crux.`);

  return NextResponse.json({ reply, reading });
}
