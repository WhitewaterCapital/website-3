// ═══════════════════════════════════════════════════════════════════════════
// IMP-03 — roles + audit trail. Pure logic, no real auth backend.
//
// This repo's README documents a single shared passcode for the whole site
// (see src/app/api/login/route.ts / src/lib/auth.ts) — there is no per-user
// identity or session-bound role anywhere in this codebase today. Everything
// below is therefore a policy module with no real enforcement point wired
// into it yet: it defines the two roles, the exact permission split, the
// two-distinct-people promotion rule, and an audit-entry shape + in-memory
// log, ready to be called from a real promotion UI once one exists. The
// pseudo-code at the bottom shows exactly how that call would look.
// ═══════════════════════════════════════════════════════════════════════════

export type Role = "research-operator" | "risk-approver";

export type PrivilegedAction =
  | "retrain-model"
  | "shadow-run-model"
  | "read-card"
  | "promote-to-live"
  | "demote-from-live"
  | "change-allocator-cap"
  | "trip-kill-switch";

// The exact split, per the doc: research operators build and evaluate models
// but never touch capital-affecting state; risk approvers are the only role
// that can move a model into (or out of) live sizing, change allocator caps,
// or trip the kill switch.
const RESEARCH_OPERATOR_ALLOWED: readonly PrivilegedAction[] = ["retrain-model", "shadow-run-model", "read-card"];
const RISK_APPROVER_ALLOWED: readonly PrivilegedAction[] = [
  "read-card",
  "promote-to-live",
  "demote-from-live",
  "change-allocator-cap",
  "trip-kill-switch",
];

export function can(action: PrivilegedAction, role: Role): boolean {
  return role === "research-operator" ? RESEARCH_OPERATOR_ALLOWED.includes(action) : RISK_APPROVER_ALLOWED.includes(action);
}

// ─────────────────────────────────────────────────────────────────────────
// Two-distinct-people rule for promotion to live sizing.
// ─────────────────────────────────────────────────────────────────────────

export interface PromotionRequest {
  modelId: string;
  requestedBy: string; // person identifier — a name/email/id, whatever a real auth system supplies
  requestedAt: string; // ISO
}

export interface PromotionGateResult {
  ok: boolean;
  reason?: string;
}

// Call this at the moment someone tries to FINALIZE a promotion (not at
// request time) — `approverIdentity` is whoever is clicking "approve" now.
export function canFinalizePromotion(req: PromotionRequest, approverRole: Role, approverIdentity: string): PromotionGateResult {
  if (!can("promote-to-live", approverRole)) {
    return { ok: false, reason: `${approverIdentity} holds role "${approverRole}", which cannot promote a model to live sizing.` };
  }
  if (approverIdentity === req.requestedBy) {
    return {
      ok: false,
      reason: "Promotion to live sizing needs two DISTINCT people — the person who requested it cannot also be the one who approves it.",
    };
  }
  return { ok: true };
}

// ─────────────────────────────────────────────────────────────────────────
// Audit trail — who / when / before / after / reason, for every privileged
// action. In-memory only; needs a real persistence layer (a DB table) before
// this survives a restart or is visible to more than one server instance —
// same "swap only the store" seam documented in graph.ts/weekly.ts/state.ts.
// ─────────────────────────────────────────────────────────────────────────

export interface AuditEntry {
  id: string;
  at: string; // ISO
  who: string;
  role: Role;
  action: PrivilegedAction;
  before: unknown;
  after: unknown;
  reason: string;
}

const auditLog: AuditEntry[] = [];
let auditSeq = 0;

export function appendAudit(entry: Omit<AuditEntry, "id" | "at"> & { at?: string }): AuditEntry {
  auditSeq += 1;
  const full: AuditEntry = { id: `audit_${auditSeq}`, at: entry.at ?? new Date().toISOString(), ...entry };
  auditLog.push(full);
  return full;
}

export function listAudit(filter?: { who?: string; action?: PrivilegedAction; role?: Role }): AuditEntry[] {
  let rows = auditLog.slice();
  if (filter?.who) rows = rows.filter((e) => e.who === filter.who);
  if (filter?.action) rows = rows.filter((e) => e.action === filter.action);
  if (filter?.role) rows = rows.filter((e) => e.role === filter.role);
  return rows;
}

// ─────────────────────────────────────────────────────────────────────────
// Pseudo-code: how a real "promote model to live" button would gate itself.
// There is no real model-promotion UI in this codebase to wire this into for
// real — this is illustrative only.
//
//   function onPromoteClick(currentUser: { id: string; role: Role }, req: PromotionRequest) {
//     if (!can("promote-to-live", currentUser.role)) {
//       return showError(`${currentUser.role} cannot promote a model to live sizing.`);
//     }
//     const gate = canFinalizePromotion(req, currentUser.role, currentUser.id);
//     if (!gate.ok) return showError(gate.reason);
//
//     const before = getCurrentAllocatorState(req.modelId);       // wherever that real state lives
//     applyPromotion(req.modelId);                                 // the real capital-affecting change
//     const after = getCurrentAllocatorState(req.modelId);
//
//     appendAudit({
//       who: currentUser.id,
//       role: currentUser.role,
//       action: "promote-to-live",
//       before,
//       after,
//       reason: `Two-person approval satisfied (requested by ${req.requestedBy}); promoting per weekly review.`,
//     });
//   }
// ─────────────────────────────────────────────────────────────────────────
