import type { Collection } from "@/types";

export type TerminalRequest = {
  id: number; invoice_number: string; customer_name: string; amount_paise: number;
  state: string; error: string | null; collection: Collection | null;
};

// Never auto-select a completed or unresolved request. A current selection always wins.
export function nextAutomaticRequest(rows: TerminalRequest[], selected: number | null, acknowledged: ReadonlySet<number> = new Set()): number | null {
  if (selected !== null) return selected;
  return rows.find((r) => !acknowledged.has(r.id) && ((r.state === "creating" && !r.collection) ||
    (r.state === "ready" && r.collection?.payment_status === "pending")))?.id ?? null;
}
