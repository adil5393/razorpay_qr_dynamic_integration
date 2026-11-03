import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Clock, IndianRupee, QrCode } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";
import { useAuth } from "@/context/AuthContext";
import { api, formatApiError } from "@/lib/api";
import { formatDateTime, formatINR } from "@/lib/format";
import type { PaymentRecord } from "@/types";

interface DashboardData {
  total_confirmed_paise: number;
  successful_payment_count: number;
  pending_qr_count: number;
  pending_qr_paise: number;
  total_qr_count: number;
  recent_payments: (PaymentRecord & { collection: { id: number; code: string; reference: string | null; customer_name: string | null } })[];
}

function Metric({ label, value, sub, icon: Icon, testId, tone }: { label: string; value: string; sub: string; icon: any; testId: string; tone: string }) {
  return (
    <div className="rounded-2xl border border-border bg-card p-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{label}</p>
        <div className={`rounded-lg p-2 ${tone}`}><Icon className="h-5 w-5" /></div>
      </div>
      <p data-testid={testId} className="mt-4 font-num text-3xl font-bold tracking-tight">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{sub}</p>
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["dashboard"],
    queryFn: async () => (await api.get<DashboardData>("/dashboard")).data,
    refetchInterval: 15000,
    staleTime: 0,
  });

  if (isLoading) return <LoadingState label="Loading dashboard…" />;
  if (error || !data) return <ErrorState message={formatApiError(error)} onRetry={() => refetch()} />;

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">Hello, {user ? user.name : ""}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {user && user.role === "admin" ? "All collections across your team." : "Collections you have created."} Figures count only Razorpay-confirmed payments.
          </p>
        </div>
        <Button asChild className="h-12 gap-2 px-6 text-base" data-testid="dashboard-new-qr-button">
          <Link to="/collect"><QrCode className="h-5 w-5" /> New QR collection</Link>
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Metric label="Total confirmed collections" value={formatINR(data.total_confirmed_paise)} sub="Captured payments verified by Razorpay"
          icon={IndianRupee} testId="metric-total-confirmed" tone="bg-emerald-500/10 text-emerald-500" />
        <Metric label="Successful payments" value={String(data.successful_payment_count)} sub={`${data.total_qr_count} QR codes generated in total`}
          icon={CheckCircle2} testId="metric-success-count" tone="bg-blue-500/10 text-blue-500" />
        <Metric label="Pending QR collections" value={String(data.pending_qr_count)} sub={`${formatINR(data.pending_qr_paise)} awaiting payment`}
          icon={Clock} testId="metric-pending-count" tone="bg-amber-500/10 text-amber-500" />
      </div>

      <section className="rounded-2xl border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="font-display text-lg font-semibold">Recent payment activity</h2>
          <Link to="/history" className="flex items-center gap-1 text-sm text-primary hover:underline" data-testid="dashboard-view-history-link">
            View history <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
        {data.recent_payments.length === 0 ? (
          <EmptyState title="No payments yet" hint="Payments appear here once Razorpay confirms them through the webhook or a status check." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="recent-payments-table">
              <thead className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                <tr><th className="px-6 py-3">Payment ID</th><th className="px-6 py-3">Collection</th><th className="px-6 py-3">Amount</th><th className="px-6 py-3">Status</th><th className="px-6 py-3">Received</th></tr>
              </thead>
              <tbody>
                {data.recent_payments.map((p) => (
                  <tr key={p.id} className="border-t border-border hover:bg-muted/50" data-testid={`recent-payment-row-${p.id}`}>
                    <td className="px-6 py-3 font-num">{p.razorpay_payment_id}</td>
                    <td className="px-6 py-3"><Link to={`/collections/${p.collection.id}`} className="font-num text-primary hover:underline">{p.collection.code}</Link>
                      <span className="ml-2 text-muted-foreground">{p.collection.reference || ""}</span></td>
                    <td className="px-6 py-3 font-num">{formatINR(p.amount_paise)}</td>
                    <td className="px-6 py-3"><StatusBadge status={p.is_successful ? "paid" : p.status} /></td>
                    <td className="px-6 py-3 font-num text-muted-foreground">{formatDateTime(p.rzp_created_at || p.first_seen_at)}</td>
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
