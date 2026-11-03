import { useEffect, useState } from "react";
import { CheckCircle2, Copy, Download, Loader2, ShieldCheck, Timer } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { api, formatApiError } from "@/lib/api";
import { copyText, formatDateTime, formatINR } from "@/lib/format";
import type { Collection, CollectionStatus } from "@/types";

function useCountdown(target: string | null) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(t); };
  }, []);
  if (!target) return null;
  const ms = new Date(target).getTime() - now;
  if (ms <= 0) return "00:00";
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function QRDisplay({ collection, live }: { collection: Collection; live?: CollectionStatus }) {
  const [downloading, setDownloading] = useState(false);
  const paymentStatus = live?.payment_status ?? collection.payment_status;
  const qrStatus = live?.qr_status ?? collection.qr_status;
  const countdown = useCountdown(live?.close_by ?? collection.close_by);
  const paid = paymentStatus === "paid";
  const payment = live?.successful_payment ?? collection.payments?.find((p) => p.is_successful);

  const onCopy = async () => {
    const ok = await copyText(collection.image_url);
    if (ok) toast.success("QR link copied"); else toast.error("Could not copy link");
  };

  const onDownload = async () => {
    setDownloading(true);
    try {
      const res = await api.get(`/collections/${collection.id}/qr-image`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${collection.code}.png`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(formatApiError(e));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div data-testid="qr-display" className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-widest text-muted-foreground">Amount to collect</p>
          <p data-testid="qr-display-amount" className="font-num text-4xl font-bold tracking-tight sm:text-5xl">{formatINR(collection.amount_paise)}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Ref: <span data-testid="qr-display-reference" className="font-num text-foreground">{collection.reference || "—"}</span>
            {collection.customer_name && <> · {collection.customer_name}</>}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <StatusBadge status={paymentStatus} testId="qr-status-badge" large />
          <span className="text-xs text-muted-foreground">QR: <StatusBadge status={qrStatus} testId="qr-razorpay-status-badge" /></span>
        </div>
      </div>

      <div className="relative mx-auto w-full max-w-sm">
        <div className="rounded-2xl border border-border bg-white p-4 shadow-sm">
          <img data-testid="qr-image" src={collection.image_url} alt={`Razorpay QR for ${formatINR(collection.amount_paise)}`}
            className={paid ? "w-full opacity-20" : "w-full"} />
        </div>
        {paid && (
          <div data-testid="payment-confirmed-overlay" className="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-2xl bg-emerald-600/95 p-6 text-center text-white">
            <CheckCircle2 className="h-16 w-16" />
            <p className="font-display text-2xl font-bold">Payment confirmed</p>
            <p className="text-sm opacity-90">Verified by Razorpay</p>
            {payment && <p className="font-num text-xs opacity-90">{payment.razorpay_payment_id}</p>}
          </div>
        )}
      </div>

      {!paid && paymentStatus === "pending" && (
        <div className="flex items-center justify-center gap-4 text-sm text-muted-foreground">
          <span className="flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Waiting for Razorpay confirmation</span>
          {countdown && qrStatus === "active" && (
            <span data-testid="qr-countdown" className="flex items-center gap-1 font-num"><Timer className="h-4 w-4" />{countdown}</span>
          )}
        </div>
      )}
      {live?.sync_error && <p data-testid="qr-sync-error" className="text-center text-xs text-rose-500">Status check issue: {live.sync_error}</p>}

      <div className="grid grid-cols-2 gap-3">
        <Button variant="outline" className="h-14 gap-2 text-base" onClick={onCopy} data-testid="copy-qr-url-button">
          <Copy className="h-5 w-5" /> Copy QR link
        </Button>
        <Button variant="outline" className="h-14 gap-2 text-base" onClick={onDownload} disabled={downloading} data-testid="download-qr-image-button">
          {downloading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Download className="h-5 w-5" />} Download
        </Button>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-border bg-muted/40 p-4 text-sm">
        <dt className="text-muted-foreground">Collection ID</dt><dd data-testid="qr-display-code" className="font-num text-right">{collection.code}</dd>
        <dt className="text-muted-foreground">Razorpay QR ID</dt><dd data-testid="qr-display-rzp-id" className="truncate font-num text-right">{collection.razorpay_qr_id}</dd>
        <dt className="text-muted-foreground">Expires</dt><dd className="font-num text-right">{formatDateTime(live?.close_by ?? collection.close_by)}</dd>
      </dl>
      <p className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
        <ShieldCheck className="h-4 w-4" /> Status only turns Paid after Razorpay confirms a captured payment.
      </p>
    </div>
  );
}
