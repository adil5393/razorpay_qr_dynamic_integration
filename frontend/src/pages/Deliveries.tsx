import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";

type Delivery = { id: number; event_id: string; collection_id: number; status: string; attempts: number; last_error: string | null; last_response_status: number | null };
export default function Deliveries() {
  const query = useQuery({ queryKey: ["odoo-deliveries"], queryFn: async () => (await api.get<Delivery[]>("/admin/odoo-deliveries")).data, refetchInterval: 10000 });
  const retry = async (id: number) => { try { await api.post(`/admin/odoo-deliveries/${id}/retry`); await query.refetch(); } catch (e) { toast.error(formatApiError(e)); } };
  return <div className="space-y-5"><h1 className="font-display text-3xl font-bold">Odoo callback delivery</h1>
    <p className="text-sm text-muted-foreground">Delivered means the receiver returned HTTP success. It does not confirm accounting reconciliation.</p>
    {query.error && <p className="text-rose-600">{formatApiError(query.error)}</p>}
    {query.isLoading && <p>Loading…</p>}
    {(query.data || []).map(d => <div key={d.id} className="rounded-xl border border-border bg-card p-4">
      <p>Collection {d.collection_id} · {d.status} · {d.attempts} attempts</p>
      <p className="break-all text-xs text-muted-foreground">{d.event_id} {d.last_error || ""}</p>
      {(d.status === "failed" || d.status === "abandoned") && <Button variant="outline" onClick={() => retry(d.id)}>Retry delivery</Button>}
    </div>)}
  </div>;
}
