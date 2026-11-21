import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { QRDisplay } from "@/components/QRDisplay";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState, LoadingState } from "@/components/States";
import { useCollectionStatus } from "@/hooks/queries";
import { api, formatApiError } from "@/lib/api";
import { formatINR } from "@/lib/format";
import type { Collection } from "@/types";

type RequestRow = { id: number; invoice_number: string; customer_name: string; amount_paise: number; state: string; error: string | null; collection: Collection | null };

function Selected({ row }: { row: RequestRow }) {
  const live = useCollectionStatus(row.collection?.id);
  return <div className="space-y-4 rounded-2xl border border-border bg-card p-6">
    <h2 className="font-display text-xl font-semibold">{row.invoice_number}</h2>
    <p>{row.customer_name} · {formatINR(row.amount_paise)}</p>
    <p className="text-xs text-muted-foreground">Request #{row.id}{row.error ? ` · ${row.error}` : ""}</p>
    {row.collection ? <QRDisplay collection={row.collection} live={live.data} /> : <p>QR unavailable: {row.state}. Contact an administrator.</p>}
  </div>;
}

export default function Terminal() {
  const [selected, setSelected] = useState<number | null>(null);
  const query = useQuery({ queryKey: ["terminal-requests"], queryFn: async () => (await api.get<RequestRow[]>("/terminal/requests")).data, refetchInterval: 5000 });
  if (query.isLoading) return <LoadingState />;
  if (query.error || !query.data) return <ErrorState message={formatApiError(query.error)} onRetry={() => query.refetch()} />;
  const row = query.data.find(r => r.id === selected);
  return <div className="space-y-6">
    <div><h1 className="font-display text-3xl font-bold">Odoo payment requests</h1><p className="mt-2 text-sm text-muted-foreground">Select a request to display its QR. Payment status updates automatically.</p></div>
    <div className="grid gap-6 lg:grid-cols-2"><div className="space-y-2">
      {query.data.length === 0 && <p>No requests received yet.</p>}
      {query.data.map(r => <button key={r.id} onClick={() => setSelected(r.id)} className="w-full rounded-xl border border-border bg-card p-4 text-left hover:bg-muted">
        <span className="font-semibold">{r.invoice_number}</span><span className="float-right"><StatusBadge status={r.collection?.payment_status || r.state} /></span>
        <span className="mt-1 block text-sm">{r.customer_name} · {formatINR(r.amount_paise)}</span>
      </button>)}
    </div>{row && <Selected row={row} />}</div>
  </div>;
}
