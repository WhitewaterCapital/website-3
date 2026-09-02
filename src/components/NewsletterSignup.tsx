"use client";

import { useState } from "react";
import { supabase } from "@/lib/supabase";

// Email capture for the letters/newsletter. Inserts straight into Supabase
// (RLS allows insert-only from the public). Duplicate emails are treated as
// success, not an error.
export function NewsletterSignup({ source = "site" }: { source?: string }) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [msg, setMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const value = email.trim().toLowerCase();
    if (!value) return;
    setState("loading");

    if (!supabase) {
      setState("error");
      setMsg("Signups aren't configured yet.");
      return;
    }
    const { error } = await supabase
      .from("newsletter_subscribers")
      .insert({ email: value, source });

    if (error && error.code !== "23505") {
      setState("error");
      setMsg("Something went wrong — try again.");
      return;
    }
    setState("done");
    setMsg(error?.code === "23505" ? "You're already on the list." : "You're in.");
  }

  if (state === "done") {
    return <p className="text-sm text-emerald-600 dark:text-emerald-400">{msg}</p>;
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
      <input
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@email.com"
        className="flex-1 border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
      />
      <button
        disabled={state === "loading"}
        className="bg-foreground px-5 py-2 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
      >
        {state === "loading" ? "…" : "Subscribe"}
      </button>
      {state === "error" ? (
        <span className="text-sm text-rose-500">{msg}</span>
      ) : null}
    </form>
  );
}
