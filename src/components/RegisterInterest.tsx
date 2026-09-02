"use client";

import { useState } from "react";
import { supabase } from "@/lib/supabase";

// "Register interest" form for prospective investors. Captures the lead so the
// team can follow up privately — deliberately NOT an offer or a subscription.
// Inserts into Supabase (RLS: insert-only from the public).
export function RegisterInterest() {
  const [form, setForm] = useState({ name: "", email: "", note: "", accredited: false });
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");

  function set<K extends keyof typeof form>(k: K, v: (typeof form)[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim() || !form.email.trim()) return;
    setState("loading");

    if (!supabase) {
      setState("error");
      return;
    }
    const { error } = await supabase.from("investor_interest").insert({
      name: form.name.trim(),
      email: form.email.trim().toLowerCase(),
      note: form.note.trim() || null,
      accredited: form.accredited,
    });
    setState(error ? "error" : "done");
  }

  if (state === "done") {
    return (
      <div className="border border-hairline bg-paper p-6">
        <p className="eyebrow">Received</p>
        <p className="mt-2 text-sm text-foreground/80">
          Thanks — we&apos;ve got your details and will reach out personally. No
          offer or commitment is made or implied by this form.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="eyebrow">Name</span>
          <input
            required
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            className="mt-1 w-full border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
          />
        </label>
        <label className="block">
          <span className="eyebrow">Email</span>
          <input
            type="email"
            required
            value={form.email}
            onChange={(e) => set("email", e.target.value)}
            className="mt-1 w-full border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
          />
        </label>
      </div>
      <label className="block">
        <span className="eyebrow">Anything you&apos;d like us to know</span>
        <textarea
          rows={3}
          value={form.note}
          onChange={(e) => set("note", e.target.value)}
          placeholder="How you heard about us, ballpark size, questions…"
          className="mt-1 w-full resize-y border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
        />
      </label>
      <label className="flex items-start gap-2 text-sm text-foreground/80">
        <input
          type="checkbox"
          checked={form.accredited}
          onChange={(e) => set("accredited", e.target.checked)}
          className="mt-1"
        />
        <span>
          I believe I qualify as an accredited investor (self-reported — not
          verification).
        </span>
      </label>

      {state === "error" ? (
        <p className="text-sm text-rose-500">Something went wrong — try again.</p>
      ) : null}

      <button
        disabled={state === "loading"}
        className="bg-foreground px-6 py-2.5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
      >
        {state === "loading" ? "Sending…" : "Register interest"}
      </button>
    </form>
  );
}
