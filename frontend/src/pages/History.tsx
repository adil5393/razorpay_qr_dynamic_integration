import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, QrCode, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";
import { api, formatApiError } from "@/lib/api";
import { formatDateTime, formatINR } from "@/lib/format";
import type { Collection } from "@/types";

const PAGE_SIZE = 20;

export default function History() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(1); }, 300);
    return () => { clearTimeout(t); };
  }, [search]);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["collections", debounced, status, page],
    queryFn: async () => (await api.get<{ items: Collection[]; total: number }>("/collections", {
      params: { search: debounced || undefined, status: status === "all" ? undefined : status, page, page_size: PAGE_SIZE },
    })).data,
    placeholderData: keepPreviousData,
    staleTime: 0,
  });

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-bold tracking-tight">QR history</h1>
        <p className="mt-1 text-sm text-muted-foreground">Every QR generated, with its Razorpay status. Amounts cannot be edited after creation.</p>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search collection ID, Razorpay QR ID, reference, customer or staff"
            className="h-12 pl-11" data-testid="history-search-input" />
        </div>
        <Select value={status} onValueChange={(v) => { setStatus(v); setPage(1); }}>
          <SelectTrigger className="h-12 sm:w-48" data-testid="history-status-filter"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all" data-testid="history-filter-all">All statuses</SelectItem>
            <SelectItem value="pending" data-testid="history-filter-pending">Pending</SelectItem>
            <SelectItem value="paid" data-testid="history-filter-paid">Paid</SelectItem>
            <SelectItem value="expired" data-testid="history-filter-expired">Expired</SelectItem>
            <SelectItem value="closed" data-testid="history-filter-closed">Closed</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="rounded-2xl border border-border bg-card">
        {isLoading ? <LoadingState /> : error ? <ErrorState message={formatApiError(error)} onRetry={() => refetch()} /> :
          !data || data.items.length === 0 ? (
            <EmptyState title={debounced || status !== "all" ? "No matching collections" : "No QR codes yet"}
              hint={debounced || status !== "all" ? "Try a different search or filter." : "Generate your first QR to start collecting."}
              action={<Button asChild className="h-11 gap-2"><Link to="/collect"><QrCode className="h-4 w-4" />New QR</Link></Button>} />
          ) : (
            <div className={`overflow-x-auto ${isFetching ? "opacity-70" : ""}`}>
              <table className="w-full text-sm" data-testid="history-table">
                <thead className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-5 py-3">Collection ID</th><th className="px-5 py-3">Razorpay QR ID</th><th className="px-5 py-3 text-right">Amount</th>
                    <th className="px-5 py-3">Reference</th><th className="px-5 py-3">Created by</th><th className="px-5 py-3">Created at</th>
                    <th className="px-5 py-3">QR status</th><th className="px-5 py-3">Payment</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((c) => (
                    <tr key={c.id} onClick={() => navigate(`/collections/${c.id}`)} className="cursor-pointer border-t border-border transition-colors hover:bg-muted/50"
                      data-testid={`history-row-${c.id}`}>
                      <td className="px-5 py-4 font-num font-medium text-primary">{c.code}</td>
                      <td className="px-5 py-4 font-num text-muted-foreground">{c.razorpay_qr_id}</td>
                      <td className="px-5 py-4 text-right font-num font-semibold">{formatINR(c.amount_paise)}</td>
                      <td className="px-5 py-4 font-num">{c.reference || "—"}{c.customer_name && <span className="block font-sans text-xs text-muted-foreground">{c.customer_name}</span>}</td>
                      <td className="px-5 py-4">{c.created_by.name}</td>
                      <td className="px-5 py-4 font-num text-muted-foreground whitespace-nowrap">{formatDateTime(c.created_at)}</td>
                      <td className="px-5 py-4"><StatusBadge status={c.qr_status} testId={`history-qr-status-${c.id}`} /></td>
                      <td className="px-5 py-4"><StatusBadge status={c.payment_status} testId={`history-payment-status-${c.id}`} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </div>

      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground" data-testid="history-total">{data.total} collections</p>
          <div className="flex items-center gap-2">
            <Button variant="outline" className="h-11" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="history-prev-page"><ChevronLeft className="h-4 w-4" /></Button>
            <span className="font-num text-sm">{page} / {pages}</span>
            <Button variant="outline" className="h-11" disabled={page >= pages} onClick={() => setPage(page + 1)} data-testid="history-next-page"><ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>
      )}
    </div>
  );
}
