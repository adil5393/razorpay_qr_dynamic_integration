import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Copy, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";
import { api, formatApiError } from "@/lib/api";
import { copyText, formatDateTime } from "@/lib/format";

interface RzpStatus {
  configured: boolean;
  mode: string | null;
  key_id_masked: string | null;
  webhook_secret_configured: boolean;
  webhook_url: string;
  webhook_events: string[];
}

interface WebhookEventRow {
  id: number; event_id: string | null; event_type: string | null; status: string; signature_valid: boolean;
  error: string | null; attempts: number; razorpay_qr_id: string | null; razorpay_payment_id: string | null; received_at: string;
}

function Check({ ok, label, testId }: { ok: boolean; label: string; testId: string }) {
  return (
    <div className="flex items-center gap-2 text-sm" data-testid={testId} data-ok={ok}>
      {ok ? <CheckCircle2 className="h-5 w-5 text-emerald-500" /> : <XCircle className="h-5 w-5 text-rose-500" />}{label}
    </div>
  );
}

export default function Settings() {
  const status = useQuery({ queryKey: ["rzp-status"], queryFn: async () => (await api.get<RzpStatus>("/admin/razorpay")).data });
  const events = useQuery({ queryKey: ["webhook-events"], queryFn: async () => (await api.get<WebhookEventRow[]>("/admin/webhook-events")).data, refetchInterval: 15000 });

  if (status.isLoading) return <LoadingState />;
  if (status.error || !status.data) return <ErrorState message={formatApiError(status.error)} onRetry={() => status.refetch()} />;
  const s = status.data;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-3xl font-bold tracking-tight">Razorpay setup</h1>
        <p className="mt-1 text-sm text-muted-foreground">Keys are stored only on the server. Secrets are never shown here or sent to the browser.</p>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="space-y-4 rounded-2xl border border-border bg-card p-6">
          <h2 className="font-display text-lg font-semibold">Connection</h2>
          <Check ok={s.configured} label={s.configured ? `API keys configured (${s.mode} mode)` : "API keys missing"} testId="rzp-keys-check" />
          <Check ok={s.webhook_secret_configured} label={s.webhook_secret_configured ? "Webhook secret configured" : "Webhook secret missing"} testId="rzp-webhook-check" />
          {s.key_id_masked && <p className="text-sm text-muted-foreground">Key ID: <span className="font-num text-foreground" data-testid="rzp-key-masked">{s.key_id_masked}</span></p>}
        </section>
        <section className="space-y-4 rounded-2xl border border-border bg-card p-6">
          <h2 className="font-display text-lg font-semibold">Webhook</h2>
          <p className="text-sm text-muted-foreground">In Razorpay Dashboard → Settings → Webhooks, add this URL with your webhook secret and select the events below.</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate rounded-lg bg-muted px-3 py-2.5 font-num text-xs" data-testid="webhook-url">{s.webhook_url}</code>
            <Button variant="outline" size="icon" className="h-11 w-11" data-testid="copy-webhook-url-button"
              onClick={async () => { if (await copyText(s.webhook_url)) toast.success("Webhook URL copied"); }}><Copy className="h-4 w-4" /></Button>
          </div>
          <div className="flex flex-wrap gap-2">{s.webhook_events.map((e) => <span key={e} className="rounded-md border border-border px-2 py-1 font-num text-xs">{e}</span>)}</div>
        </section>
      </div>
      <section className="rounded-2xl border border-border bg-card">
        <h2 className="border-b border-border px-6 py-4 font-display text-lg font-semibold">Recent webhook events</h2>
        {events.isLoading ? <LoadingState /> : !events.data || events.data.length === 0 ? (
          <EmptyState title="No webhook events received yet" hint="Events appear here once Razorpay starts calling the webhook URL." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="webhook-events-table">
              <thead className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                <tr><th className="px-5 py-3">Received</th><th className="px-5 py-3">Event</th><th className="px-5 py-3">Event ID</th><th className="px-5 py-3">QR / Payment</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Error</th></tr>
              </thead>
              <tbody>
                {events.data.map((e) => (
                  <tr key={e.id} className="border-t border-border align-top" data-testid={`webhook-event-row-${e.id}`}>
                    <td className="px-5 py-3 font-num text-muted-foreground whitespace-nowrap">{formatDateTime(e.received_at)}</td>
                    <td className="px-5 py-3 font-num">{e.event_type || "—"}</td>
                    <td className="px-5 py-3 font-num text-xs">{e.event_id || "—"}{e.attempts > 1 && <span className="ml-1 text-muted-foreground">×{e.attempts}</span>}</td>
                    <td className="px-5 py-3 font-num text-xs">{e.razorpay_qr_id || "—"}<br />{e.razorpay_payment_id || ""}</td>
                    <td className="px-5 py-3"><StatusBadge status={e.status} /></td>
                    <td className="max-w-xs px-5 py-3 text-xs text-rose-500">{e.error || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
