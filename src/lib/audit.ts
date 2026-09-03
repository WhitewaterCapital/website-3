// ---------------------------------------------------------------------------
// Audit log for privileged model-ops actions (IMP-03).
//
// "Every privileged action writes a permanent audit entry with who, when,
//  before, after and a written reason."
//
// SCOPE / KNOWN GAP: this is an in-memory, append-only log. That matches
// what this sandbox can actually provide — there is no database wired up
// for this feature — but it is NOT sufficient for production. A real
// deployment needs a persistent, tamper-evident store (e.g. a database
// table this application role has INSERT-only privilege on — no UPDATE, no
// DELETE) so the log survives restarts and cannot be edited after the fact
// even by someone with database access. That persistence layer is out of
// scope here; this module is written so swapping the in-memory array for a
// real insert-only store is a small, contained change (the public API is
// already just `record` + read methods, mirroring an append-only table).
//
// Also see the blocked-dependency note in roles.ts: until a real per-member
// auth provider exists, `performedBy` cannot be populated from a real
// session — a future call site supplies it once that identity exists.
// ---------------------------------------------------------------------------

import { canPerform, PROMOTION_REQUIRES_APPROVERS, type Action, type Role } from "./roles";

export interface AuditEntry {
  id: string;
  action: Action;
  /** Person id, or an array of ids for actions requiring multiple approvers (e.g. promotion). */
  performedBy: string | string[];
  /** ISO 8601 timestamp. */
  timestamp: string;
  /** State before the action. Opaque/JSON — shape is up to the caller. */
  before: unknown;
  /** State after the action. Opaque/JSON — shape is up to the caller. */
  after: unknown;
  /** Required, non-empty written justification for the action. */
  reason: string;
}

let nextId = 1;

function generateId(): string {
  // Simple monotonic id, sufficient for an in-memory log. A real persistent
  // store would use its own primary key (uuid, serial, etc).
  return `audit_${Date.now()}_${nextId++}`;
}

/**
 * Checks that a promote_model entry's `performedBy` carries at least
 * PROMOTION_REQUIRES_APPROVERS distinct ids, each holding a role that grants
 * "promote_model". Mirrors `isValidPromotionApproval` in roles.ts (kept as a
 * separate check here, rather than a shared call, so this module enforces
 * the rule at write time even if a caller bypasses roles.ts entirely) —
 * cross-reference roles.ts's `isValidPromotionApproval` for the canonical
 * approval-validation logic used before an action is attempted.
 */
function assertValidPromotionApprovers(
  performedBy: string | string[],
  approverRolesById?: Record<string, Role[]>,
): void {
  if (!Array.isArray(performedBy)) {
    throw new Error(
      `Cannot record "promote_model": performedBy must be an array of at least ${PROMOTION_REQUIRES_APPROVERS} distinct approver ids, got a single id.`,
    );
  }

  const distinct = new Set(performedBy);
  if (distinct.size !== performedBy.length) {
    throw new Error('Cannot record "promote_model": duplicate approver id in performedBy.');
  }
  if (distinct.size < PROMOTION_REQUIRES_APPROVERS) {
    throw new Error(
      `Cannot record "promote_model": requires ${PROMOTION_REQUIRES_APPROVERS} distinct named approvers, got ${distinct.size}.`,
    );
  }

  if (approverRolesById) {
    for (const id of distinct) {
      const roles = approverRolesById[id] ?? [];
      if (!canPerform(roles, "promote_model")) {
        throw new Error(
          `Cannot record "promote_model": approver "${id}" does not hold the risk_approver role.`,
        );
      }
    }
  }
}

/**
 * Append-only audit log. Deliberately exposes no update/delete-shaped
 * method at all — not even a private one — so the type surface itself makes
 * tampering impossible from this module's own API. Only `record` (write)
 * and `list` / `getById` (read) exist.
 */
export class AuditLog {
  private entries: AuditEntry[] = [];

  /**
   * Records one audit entry. Throws (does not silently drop or fix up the
   * entry) when:
   *   - `reason` is missing or empty/whitespace-only.
   *   - `action` is "promote_model" and `performedBy` is not an array of at
   *     least PROMOTION_REQUIRES_APPROVERS distinct ids (optionally further
   *     validated against `approverRolesById` when supplied).
   *
   * `approverRolesById` is optional and only consulted for promote_model —
   * pass it when the caller has the role lookup available so the role check
   * happens here too, not only in roles.ts.
   */
  record(
    entry: Omit<AuditEntry, "id" | "timestamp">,
    approverRolesById?: Record<string, Role[]>,
  ): AuditEntry {
    if (!entry.reason || entry.reason.trim().length === 0) {
      throw new Error(`Cannot record audit entry for "${entry.action}": a written reason is required.`);
    }

    if (entry.action === "promote_model") {
      assertValidPromotionApprovers(entry.performedBy, approverRolesById);
    }

    const full: AuditEntry = {
      ...entry,
      id: generateId(),
      timestamp: new Date().toISOString(),
    };

    this.entries.push(full);
    return full;
  }

  /** Returns a snapshot array of all entries, oldest first. */
  list(): AuditEntry[] {
    return [...this.entries];
  }

  /** Looks up a single entry by id, or undefined if not found. */
  getById(id: string): AuditEntry | undefined {
    return this.entries.find((e) => e.id === id);
  }
}
