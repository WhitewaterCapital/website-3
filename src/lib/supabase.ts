import { createClient } from "@supabase/supabase-js";

// Supabase client for the dedicated "four-and-co" project.
// Uses the publishable (anon) key — safe in the browser because row-level
// security only permits INSERTs from the public, never reads. Submissions are
// readable only from the Supabase dashboard or a server with the secret key.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const supabaseReady = Boolean(url && anonKey);

export const supabase = supabaseReady
  ? createClient(url!, anonKey!, { auth: { persistSession: false } })
  : null;
