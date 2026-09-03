// ---------------------------------------------------------------------------
// Authorization model for privileged model-ops actions (IMP-03).
//
// SCOPE: this module implements the AUTHORIZATION MODEL only — pure,
// side-effect-free permission logic. It is NOT wired into any real request
// or session yet, and it cannot be, today:
//
//   `src/lib/auth.ts` is an explicitly-flagged placeholder — a single shared
//   passcode with no individual accounts and an unsigned cookie. There is no
//   per-user identity anywhere in this codebase right now, so there is no
//   real "current person" to hand to `canPerform` / `assertCanPerform`, and
//   no real actor id to write into an audit entry's `performedBy`.
//
// Wiring `assertCanPerform` and `AuditLog.record` (see audit.ts) into actual
// API routes and UI is therefore a GENUINELY BLOCKED dependency, not a
// shortcut taken in this pass: it requires standing up a real per-member auth
// provider (Clerk, Auth.js/NextAuth, or Supabase Auth, per auth.ts's own
// comment) with real credentials, which this sandbox does not have. Once a
// real auth provider exists and produces a real person id + their role(s),
// a call site simply looks up that person's `Role[]` and passes it in here —
// nothing in this file needs to change.
// ---------------------------------------------------------------------------

/**
 * A person's role(s). Modeled as an array everywhere permissions are checked
 * (never a single `role` field) because a real per-person system may grant
 * one person more than one role (e.g. someone who is both a research
 * operator and a risk approver).
 */
export type Role = "research_operator" | "risk_approver";

/**
 * All privileged actions this authorization model governs. Every one of
 * these is expected to eventually call `assertCanPerform` at its real call
 * site, and every one of these is expected to be written to the audit log
 * (see audit.ts) when performed.
 */
export type Action =
  | "retrain_model"
  | "start_shadow_run"
  | "read_model_card"
  | "promote_model"
  | "demote_model"
  | "change_allocator_cap"
  | "change_allocator_floor"
  | "trip_kill_switch";

/**
 * The exact permission grants from IMP-03:
 *
 *   "Research operator can retrain, start shadow runs and read model cards.
 *    Cannot promote anything and cannot touch allocator limits."
 *
 *   "Risk approver can promote and demote, change caps and floors, and trip
 *    the kill switch."
 *
 * research_operator is deliberately NOT given promote_model, demote_model,
 * change_allocator_cap, or change_allocator_floor — that omission is the
 * literal mechanism behind "a research operator cannot promote a model
 * through any code path."
 */
export const ROLE_PERMISSIONS: Record<Role, Action[]> = {
  research_operator: ["retrain_model", "start_shadow_run", "read_model_card"],
  risk_approver: [
    "promote_model",
    "demote_model",
    "change_allocator_cap",
    "change_allocator_floor",
    "trip_kill_switch",
  ],
};

/**
 * Pure permission check: does at least one of this person's roles grant the
 * given action?
 */
export function canPerform(personRoles: Role[], action: Action): boolean {
  return personRoles.some((role) => ROLE_PERMISSIONS[role]?.includes(action));
}

/**
 * Guard version of `canPerform` — the enforcement point a real call site
 * (once real identity exists) is meant to call before performing a
 * privileged action. Throws instead of returning false.
 *
 * This is this ticket's literal acceptance test: calling
 * `assertCanPerform(["research_operator"], "promote_model")` MUST throw.
 * Likewise for allocator actions — a research_operator must never be able to
 * reach `change_allocator_cap` / `change_allocator_floor` through this guard.
 */
export function assertCanPerform(personRoles: Role[], action: Action): void {
  if (!canPerform(personRoles, action)) {
    throw new Error(
      `Not authorized: role(s) [${personRoles.join(", ") || "none"}] cannot perform "${action}".`,
    );
  }
}

/** "Promotion to live sizing needs two people." */
export const PROMOTION_REQUIRES_APPROVERS = 2;

/**
 * Validates a set of named approvers for a model promotion.
 *
 * Requires:
 *   - at least PROMOTION_REQUIRES_APPROVERS distinct approver ids, AND
 *   - every one of those ids individually holds a role that grants
 *     "promote_model" (i.e. risk_approver).
 *
 * This is the concrete mechanism enforcing "every promotion in the log
 * carries two named approvers" — a single approver, or one real approver
 * paired with a research_operator, both fail with a clear reason.
 */
export function isValidPromotionApproval(
  approverIds: string[],
  approverRolesById: Record<string, Role[]>,
): { valid: boolean; reason?: string } {
  const distinctIds = new Set(approverIds);

  if (distinctIds.size !== approverIds.length) {
    return {
      valid: false,
      reason: "Duplicate approver id supplied — two distinct approvers are required.",
    };
  }

  if (distinctIds.size < PROMOTION_REQUIRES_APPROVERS) {
    return {
      valid: false,
      reason: `Promotion requires ${PROMOTION_REQUIRES_APPROVERS} distinct named approvers; got ${distinctIds.size}.`,
    };
  }

  for (const id of distinctIds) {
    const roles = approverRolesById[id] ?? [];
    if (!canPerform(roles, "promote_model")) {
      return {
        valid: false,
        reason: `Approver "${id}" does not hold the risk_approver role and cannot approve a promotion.`,
      };
    }
  }

  return { valid: true };
}
