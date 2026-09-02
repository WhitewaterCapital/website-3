// ---------------------------------------------------------------------------
// Placeholder auth for the members area.
//
// This is a shared-passcode gate so the private pages are usable today without
// standing up a full auth system. It is NOT real authentication — there are no
// individual accounts and the cookie is not signed. Before going live, swap
// this for per-member auth (Clerk, Auth.js/NextAuth, or Supabase Auth) so each
// person logs in as themselves and you get real roles + an audit trail.
// ---------------------------------------------------------------------------

export const AUTH_COOKIE = "hf_member";

// The passcode everyone on the team shares. Override with MEMBER_PASSCODE.
export function memberPasscode(): string {
  return process.env.MEMBER_PASSCODE ?? "letmein";
}

export function isValidPasscode(input: string): boolean {
  return input.trim() === memberPasscode();
}
