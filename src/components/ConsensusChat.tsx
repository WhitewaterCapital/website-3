"use client";

import { useState } from "react";

type Msg = { role: "you" | "bot"; text: string };

// Consensus chat — the desk talks to a bot that reads the day's macro model
// output, to converge on a shared view. Non-streaming for now; the API route
// is the seam where a streaming LLM plugs in.
export function ConsensusChat() {
  const [msgs, setMsgs] = useState<Msg[]>([
    {
      role: "bot",
      text: "I'm reading today's macro model output. Ask me where the desk should lean and I'll frame the crux.",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || busy) return;
    setMsgs((m) => [...m, { role: "you", text: message }]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      const data = await res.json();
      setMsgs((m) => [...m, { role: "bot", text: data.reply ?? "…" }]);
    } catch {
      setMsgs((m) => [...m, { role: "bot", text: "Couldn't reach the model." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto">
        {msgs.map((m, i) => (
          <div
            key={i}
            className={m.role === "you" ? "text-right" : "text-left"}
          >
            <span
              className={`inline-block max-w-[85%] px-3 py-2 text-sm ${
                m.role === "you"
                  ? "bg-foreground text-background"
                  : "border border-hairline bg-background"
              }`}
            >
              {m.text}
            </span>
          </div>
        ))}
      </div>
      <form onSubmit={send} className="mt-4 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Where should we lean this week?"
          className="flex-1 border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
        />
        <button
          disabled={busy}
          className="bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}
