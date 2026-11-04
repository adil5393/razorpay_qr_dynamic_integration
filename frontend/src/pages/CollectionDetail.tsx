import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, Loader2, Lock, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { QRDisplay } from "@/components/QRDisplay";
import { StatusBadge } from "@/components/StatusBadge";
import { TestModeBanner } from "@/components/TestModeBanner";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";
import { useCollectionStatus } from "@/hooks/queries";
import { api, formatApiError } from "@/lib/api";
import { formatDateTime, formatINR } from "@/lib/format";
import type { Collection } from "@/types";

export default function CollectionDetail() {
  const { id } = useParams();
  const cid = Number(id);
  const qc = useQueryClient();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["collection", cid],
    queryFn: async () => (await api.get<Collection>(`/collections/${cid}`)).data,
    enabled: !!cid,
    staleTime: 0,
  });
  const { data: live, refetch: refetchStatus, isFetching } = useCollectionStatus(data ? cid : undefined);
  const [cancelling, setCancelling] = useState(false);

  const onCancel = async () => {
    setCancelling(true);
    try {
      await api.post(`/collections/${cid}/cancel`);
      toast.success("QR cancelled. It can no longer be paid.");
    } catch (e) {
      // 409 = already paid / expired (incl. a payment that beat the cancel); 424 = Razorpay problem, QR may still be payable.
      toast.error(formatApiError(e));
    } finally {
      setCancelling(false);
      qc.invalidateQueries({ queryKey: ["collection", cid] });
      qc.invalidateQueries({ queryKey: ["collection-status", cid] });
    }
  };

  useEffect(() => {
    if (live && data && (live.payment_status !== data.payment_status || live.qr_status !== data.qr_status)) {
      qc.invalidateQueries({ queryKey: ["collection", cid] });
    }
  }, [live, data, cid, qc]);

  if (isLoading) return <LoadingState />;
  if (error || !data) return <ErrorState message={formatApiError(error)} onRetry={() => refetch()} />;

  const info: [string, string][] = [
    ["Description", data.description],
    ["Customer", data.customer_name || "—"],
    ["Created by", data.created_by.name],
    ["Created at", formatDateTime(data.created_at)],
    ["Closed at", formatDateTime(data.closed_at)],
    ["Close reason", data.close_reason || "—"],
    ["Amount received", formatINR(data.amount_received_paise)],
    ["Last checked with Razorpay", formatDateTime(live?.last_synced_at ?? data.last_synced_at)],
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="ghost" className="h-11 gap-2 px-3" data-testid="detail-back-button">
          <Link to="/history"><ArrowLeft className="h-4 w-4" /> Back to history</Link>
        </Button>
        <div className="flex flex-wrap gap-2">
          {(live?.payment_status ?? data.payment_status) === "pending" && (live?.qr_status ?? data.qr_status) === "active" && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" className="h-11 gap-2 text-rose-600 hover:text-rose-700" disabled={cancelling} data-testid="detail-cancel-qr-button">
                  {cancelling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Ban className="h-4 w-4" />} Cancel QR
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Cancel this QR?</AlertDialogTitle>
                  <AlertDialogDescription>
                    The QR for {formatINR(data.amount_paise)} will be closed at Razorpay and can no longer be paid.
                    If the customer has already paid, the payment is kept and the collection is marked paid instead.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel data-testid="cancel-qr-dismiss">Keep QR</AlertDialogCancel>
                  <AlertDialogAction onClick={onCancel} className="bg-rose-600 hover:bg-rose-700" data-testid="cancel-qr-confirm">
                    Cancel QR
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
          <Button variant="outline" className="h-11 gap-2" onClick={() => refetchStatus()} disabled={isFetching} data-testid="detail-refresh-status-button">
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} /> Check status
          </Button>
        </div>
      </div>
      <TestModeBanner />
      <div className="grid gap-8 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)]">
        <section className="rounded-2xl border border-border bg-card p-6 sm:p-8"><QRDisplay collection={data} live={live} /></section>
        <section className="space-y-6">
          <div className="rounded-2xl border border-border bg-card p-6">
            <h2 className="font-display text-lg font-semibold">Details</h2>
            <dl className="mt-4 space-y-3 text-sm">
              {info.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4"><dt className="text-muted-foreground">{k}</dt><dd className="text-right">{v}</dd></div>
              ))}
            </dl>
            <p className="mt-5 flex items-center gap-2 text-xs text-muted-foreground"><Lock className="h-3.5 w-3.5" /> The amount of an existing QR cannot be changed.</p>
          </div>
          <div className="rounded-2xl border border-border bg-card">
            <h2 className="border-b border-border px-6 py-4 font-display text-lg font-semibold">Payment history</h2>
            {!data.payments || data.payments.length === 0 ? (
              <EmptyState title="No payments recorded" hint="Payments are added only when Razorpay reports them." />
            ) : (
              <ul className="divide-y divide-border" data-testid="payment-history-list">
                {data.payments.map((p) => (
                  <li key={p.id} className="space-y-1 px-6 py-4" data-testid={`payment-history-item-${p.id}`}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-num text-sm">{p.razorpay_payment_id}</span>
                      <StatusBadge status={p.is_successful ? "paid" : p.status} testId={`payment-status-${p.id}`} />
                    </div>
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span className="font-num">{formatINR(p.amount_paise)} · {p.method || "—"}{p.vpa ? ` · ${p.vpa}` : ""}</span>
                      <span className="font-num">{formatDateTime(p.rzp_created_at || p.first_seen_at)}</span>
                    </div>
                    {p.error_description && <p className="text-xs text-rose-500">{p.error_description}</p>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
