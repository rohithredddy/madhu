import type { Role } from "../api/types";
import { roleLabel } from "../lib/format";

/** The role of a service, in its role colour and in words (never colour alone). */
export function RoleBadge({ role }: { role: Role }) {
  return <span className={`badge role-${role}`}>{roleLabel(role)}</span>;
}
