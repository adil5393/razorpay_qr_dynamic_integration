import { cn } from "@/lib/utils";

const TONES = {
  green: "bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950/80 dark:text-emerald-400 dark:border-emerald-800",
  amber: "bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950/80 dark:text-amber-400 dark:border-amber-800",
  red: "bg-rose-100 text-rose-800 border-rose-300 dark:bg-rose-950/80 dark:text-rose-400 dark:border-rose-800",
  slate: "bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700",
  blue: "bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-950/80 dark:text-blue-300 dark:border-blue-800",
};
const DOTS = { green: "bg-emerald-500", amber: "bg-amber-500", red: "bg-rose-500", slate: "bg-slate-400", blue: "bg-blue-500" };

const MAP: Record<string, { tone: keyof typeof TONES; label: string }> = {
  paid: { tone: "green", label: "Paid" },
  captured: { tone: "green", label: "Captured" },
  pending: { tone: "amber", label: "Pending" },
  authorized: { tone: "amber", label: "Authorized" },
  created: { tone: "amber", label: "Created" },
  active: { tone: "blue", label: "Active" },
  expired: { tone: "red", label: "Expired" },
  failed: { tone: "red", label: "Failed" },
  rejected: { tone: "red", label: "Rejected" },
  closed: { tone: "slate", label: "Closed" },
  processed: { tone: "green", label: "Processed" },
  ignored: { tone: "slate", label: "Ignored" },
  unmatched: { tone: "red", label: "Unmatched" },
  received: { tone: "amber", label: "Received" },
  inactive: { tone: "slate", label: "Inactive" },
};

export function StatusBadge({ status, testId, large }: { status: string; testId?: string; large?: boolean }) {
  const s = MAP[status] || { tone: "slate" as const, label: status };
  return (
    <span
      data-testid={testId}
      data-status={status}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-semibold uppercase tracking-wide whitespace-nowrap",
        large ? "px-3.5 py-1.5 text-sm" : "px-2.5 py-0.5 text-[11px]",
        TONES[s.tone],
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", DOTS[s.tone], status === "pending" && "animate-pulse")} />
      {s.label}
    </span>
  );
}
