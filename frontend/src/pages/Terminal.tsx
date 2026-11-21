import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Bell, Check, CheckCircle2, ChevronRight, Copy, Expand, Loader2, QrCode, Search, Smartphone, Volume2, VolumeX, WifiOff, X } from "lucide-react";
import { toast } from "sonner";
import { QRDisplay } from "@/components/QRDisplay";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState, LoadingState } from "@/components/States";
import { Button } from "@/components/ui/button";
import { useCollectionStatus } from "@/hooks/queries";
import { useAuth } from "@/context/AuthContext";
import { api, formatApiError } from "@/lib/api";
import { copyText, formatDateTime, formatINR } from "@/lib/format";
import { nextAutomaticRequest } from "./terminalQueue";
import type { TerminalRequest } from "./terminalQueue";

type RequestRow = TerminalRequest;
// Request IDs only, in memory; no authenticated payment data is persisted.
const acknowledgedByUser = new Map<number, Set<number>>();
const activeByUser = new Map<number, number>();
function isPending(row: RequestRow) {
  return (row.state === "creating" && !row.collection) || (row.state === "ready" && row.collection?.payment_status === "pending");
}
function tone() {
  try {
    const context = new AudioContext(); const osc = context.createOscillator(); const gain = context.createGain();
    osc.connect(gain); gain.connect(context.destination); osc.frequency.value = 740;
    gain.gain.setValueAtTime(0.06, context.currentTime); gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.25);
    osc.start(); osc.stop(context.currentTime + 0.25); osc.onended = () => { void context.close(); };
  } catch { /* Optional sound may be blocked by the browser. */ }
}
function Connection() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => { const update = () => setOnline(navigator.onLine); window.addEventListener("online", update); window.addEventListener("offline", update); return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); }; }, []);
  return <span className={"inline-flex items-center gap-2 text-xs font-medium " + (online ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600")}>{online ? <span className="h-2 w-2 rounded-full bg-emerald-500" /> : <WifiOff className="h-3.5 w-3.5" />}{online ? "Device online" : "Device offline"}</span>;
}
function CopyButton({ value, label }: { value: string; label: string }) {
  return <button type="button" onClick={async () => { if (await copyText(value)) toast.success(label + " copied"); }} className="inline-flex items-center gap-1.5 text-left text-primary hover:underline" aria-label={"Copy " + label}>{value} <Copy className="h-3.5 w-3.5 shrink-0" /></button>;
}
function WakeControl() {
  const [awake, setAwake] = useState(false);
  const lock = useRef<{ release: () => Promise<void>; addEventListener: (name: string, cb: () => void) => void } | null>(null);
  useEffect(() => () => { void lock.current?.release(); }, []);
  if (!("wakeLock" in navigator)) return null;
  const toggle = async () => {
    if (lock.current) { await lock.current.release(); lock.current = null; setAwake(false); return; }
    try { const sentinel = await (navigator as any).wakeLock.request("screen"); lock.current = sentinel; setAwake(true); sentinel.addEventListener("release", () => { lock.current = null; setAwake(false); }); }
    catch { toast.error("Screen awake is unavailable on this device."); }
  };
  return <button onClick={toggle} className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-border px-3 text-xs font-medium" aria-pressed={awake}><Smartphone className="h-4 w-4" /> {awake ? "Screen awake on" : "Keep screen awake"}</button>;
}

export default function Terminal() {
  const { user } = useAuth();
  const userId = user ? user.id : 0;
  if (!acknowledgedByUser.has(userId)) acknowledgedByUser.set(userId, new Set<number>());
  const acknowledged = acknowledgedByUser.get(userId)!;
  const [selected, setSelected] = useState<number | null>(() => activeByUser.get(userId) ?? null);
  const [snapshot, setSnapshot] = useState<RequestRow | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "pending" | "paid">("all");
  const [fullscreen, setFullscreen] = useState(false);
  const [sound, setSound] = useState(false);
  const [vibrate, setVibrate] = useState(false);
  const [params, setParams] = useSearchParams();
  const seen = useRef<Set<number> | null>(null);
  const wasPaid = useRef(false);
  const query = useQuery({ queryKey: ["terminal-requests"], queryFn: async () => (await api.get<RequestRow[]>("/terminal/requests")).data, refetchInterval: 5000 });
  const rows = query.data || [];
  const current = rows.find((r) => r.id === selected) || (snapshot?.id === selected ? snapshot : null);
  const live = useCollectionStatus(current?.collection?.id);
  const paymentStatus = live.data?.payment_status ?? current?.collection?.payment_status;
  const qrStatus = live.data?.qr_status ?? current?.collection?.qr_status;
  const paid = paymentStatus === "paid";
  const payment = live.data?.successful_payment ?? current?.collection?.payments?.find((p) => p.is_successful);
  const waiting = rows.filter((r) => isPending(r) && r.id !== selected && !acknowledged.has(r.id));
  const queueView = params.get("view") === "queue";

  useEffect(() => {
    if (!query.data) return;
    const next = nextAutomaticRequest(query.data, selected, acknowledged);
    if (selected === null && next !== null) { activeByUser.set(userId, next); setSelected(next); setParams({}); }
    const ids = new Set(query.data.map((r) => r.id));
    if (seen.current) {
      const arrivals = query.data.filter((r) => !seen.current!.has(r.id) && isPending(r));
      if (arrivals.length) {
        toast.info(arrivals.length === 1 ? "New payment request received" : arrivals.length + " new payment requests received");
        if (sound) tone(); if (vibrate && navigator.vibrate) navigator.vibrate([120, 60, 120]);
      }
    }
    seen.current = ids;
  }, [query.data, selected, sound, vibrate, userId, setParams, acknowledged]);
  useEffect(() => { const row = query.data?.find((r) => r.id === selected); if (row) setSnapshot(row); }, [query.data, selected]);
  useEffect(() => { window.dispatchEvent(new CustomEvent("uqc:queue-count", { detail: waiting.length })); }, [waiting.length]);
  useEffect(() => { if (paid || qrStatus !== "active") setFullscreen(false); }, [paid, qrStatus]);
  useEffect(() => { if (paid && !wasPaid.current) setParams({}); wasPaid.current = paid; }, [paid, setParams]);
  useEffect(() => { if (!fullscreen) return; const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setFullscreen(false); }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [fullscreen]);

  const select = (row: RequestRow) => {
    if (paid && row.id !== selected) { toast.info("Acknowledge the confirmed payment first."); return; }
    activeByUser.set(userId, row.id); setSnapshot(row); setSelected(row.id); setParams({});
  };
  const clear = () => { if (selected !== null) acknowledged.add(selected); activeByUser.delete(userId); setSnapshot(null); setSelected(null); setFullscreen(false); };
  const matching = rows.filter((r) => {
    const term = search.trim().toLowerCase();
    return (!term || [r.invoice_number, r.customer_name, String(r.id)].some((v) => v.toLowerCase().includes(term))) && (filter === "all" || (filter === "pending" ? isPending(r) : r.collection?.payment_status === "paid"));
  });
  if (query.isLoading && !query.data) return <LoadingState label="Loading payment requests…" />;
  if (query.error && !query.data) return <div className="space-y-4"><Connection /><ErrorState message={formatApiError(query.error)} onRetry={() => query.refetch()} /></div>;

  return <div className="space-y-5 pb-3">
    <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">UniversalQR / Counter</p><h1 className="mt-1 font-display text-3xl font-bold tracking-tight sm:text-4xl">Payment terminal</h1><p className="mt-1 text-sm text-muted-foreground">Odoo requests, ready for your counter.</p></div><div className="flex flex-wrap items-center gap-3"><Connection /><span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-2 text-xs font-bold text-primary"><Bell className="h-3.5 w-3.5" /> {waiting.length} in queue</span></div></div>
    {query.error && <div role="alert" className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">Unable to refresh requests. Showing the last response. <button className="underline" onClick={() => query.refetch()}>Retry</button></div>}
    <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-border bg-card p-3"><span className="mr-1 text-xs font-bold uppercase tracking-wide text-muted-foreground">Alerts</span><button className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-border px-3 text-xs font-medium" aria-pressed={sound} onClick={() => { if (!sound) tone(); setSound(!sound); }}>{sound ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />} Sound {sound ? "on" : "off"}</button>{"vibrate" in navigator && <button className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-border px-3 text-xs font-medium" aria-pressed={vibrate} onClick={() => { if (!vibrate) navigator.vibrate(80); setVibrate(!vibrate); }}><Smartphone className="h-4 w-4" /> Vibration {vibrate ? "on" : "off"}</button>}<WakeControl /></div>
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.8fr)]">
      <section className={queueView ? "hidden lg:block" : "block"} aria-label="Selected payment">
        {!current ? <div className="flex min-h-[420px] flex-col items-center justify-center rounded-3xl border border-dashed border-border bg-card p-8 text-center"><div className="grid h-20 w-20 place-items-center rounded-3xl bg-primary/10 text-primary"><QrCode className="h-10 w-10" /></div><h2 className="mt-6 font-display text-2xl font-bold">Ready for the next payment</h2><p className="mt-2 max-w-xs text-sm text-muted-foreground">An incoming request will open here automatically. You can also choose one from the queue.</p><Button variant="outline" className="mt-6 lg:hidden" onClick={() => setParams({ view: "queue" })}>View queue</Button></div> :
        <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm"><div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-7"><div><p className="text-xs font-bold uppercase tracking-[0.16em] text-muted-foreground">Current request</p><p className="mt-1 font-display font-semibold">{current.customer_name}</p></div><StatusBadge status={paymentStatus || current.state} /></div>
          {paid ? <div className="uqc-success flex min-h-[400px] flex-col items-center justify-center bg-emerald-500/5 p-7 text-center" role="status"><div className="grid h-20 w-20 place-items-center rounded-full bg-emerald-500 text-white shadow-lg shadow-emerald-500/25"><CheckCircle2 className="h-12 w-12" /></div><p className="mt-5 text-xs font-bold uppercase tracking-[0.2em] text-emerald-600 dark:text-emerald-400">Razorpay confirmed</p><h2 className="mt-2 font-display text-3xl font-bold">Payment received</h2><p className="mt-3 font-num text-3xl font-bold">{formatINR(current.amount_paise)}</p><p className="mt-2 text-sm text-muted-foreground">{current.customer_name}</p><div className="mt-5 space-y-2 text-sm"><p>Invoice: <CopyButton value={current.invoice_number} label="invoice number" /></p>{payment && <p>Payment: <CopyButton value={payment.razorpay_payment_id} label="payment reference" /></p>}</div><Button className="mt-7 h-12 w-full max-w-xs gap-2" onClick={clear}><Check className="h-4 w-4" /> Done, next payment</Button></div> :
          !current.collection ? <div className="flex min-h-[400px] flex-col items-center justify-center p-7 text-center"><div className="grid h-20 w-20 place-items-center rounded-3xl bg-primary/10 text-primary">{current.state === "creating" ? <Loader2 className="h-9 w-9 animate-spin" /> : <QrCode className="h-9 w-9" />}</div><h2 className="mt-6 font-display text-2xl font-bold">{current.state === "creating" ? "Preparing your QR" : "QR unavailable"}</h2><p className="mt-2 max-w-xs text-sm text-muted-foreground">{current.state === "creating" ? "The request will appear here as soon as the QR is ready." : "Contact an administrator to investigate this request."}</p><p className="mt-4 text-sm">Invoice: <CopyButton value={current.invoice_number} label="invoice number" /></p><p className="mt-1 font-num text-2xl font-bold">{formatINR(current.amount_paise)}</p>{current.state !== "creating" && <Button variant="outline" className="mt-6" onClick={clear}>Clear selection</Button>}</div> :
          <div className="p-5 sm:p-7"><div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-sm"><span>Invoice: <CopyButton value={current.invoice_number} label="invoice number" /></span>{paymentStatus === "pending" && qrStatus === "active" && <Button variant="outline" size="sm" className="gap-2" onClick={() => setFullscreen(true)}><Expand className="h-4 w-4" /> Full screen</Button>}</div><QRDisplay collection={current.collection} live={live.data} />{paymentStatus !== "pending" && <Button variant="outline" className="mt-5 w-full" onClick={clear}>Clear selection</Button>}</div>}
        </div>}
      </section>
      <section className={"rounded-3xl border border-border bg-card " + (queueView ? "block" : "hidden lg:block")} aria-label="Payment queue"><div className="border-b border-border p-5"><div className="flex items-center justify-between"><div><p className="text-xs font-bold uppercase tracking-[0.16em] text-muted-foreground">Incoming</p><h2 className="mt-1 font-display text-xl font-bold">Payment queue</h2></div><span className="rounded-xl bg-primary/10 px-3 py-2 font-num text-sm font-bold text-primary">{waiting.length}</span></div><div className="relative mt-4"><Search className="absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search invoice or customer" className="h-11 w-full rounded-xl border border-input bg-background pl-10 pr-3 text-sm outline-none focus:ring-2 focus:ring-ring" /></div><div className="mt-3 flex gap-2">{(["all", "pending", "paid"] as const).map((value) => <button key={value} onClick={() => setFilter(value)} aria-pressed={filter === value} className={"min-h-[40px] rounded-lg px-3 text-xs font-semibold capitalize " + (filter === value ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>{value}</button>)}</div></div>
        <div className="max-h-[680px] overflow-y-auto p-3">{matching.length === 0 ? <div className="px-4 py-12 text-center"><p className="font-semibold">No matching requests</p><p className="mt-1 text-sm text-muted-foreground">New requests from Odoo will appear here.</p></div> : matching.map((row) => <button key={row.id} onClick={() => select(row)} className={"mb-1 flex w-full items-center gap-3 rounded-2xl p-4 text-left transition-colors " + (selected === row.id ? "bg-primary/10 ring-1 ring-primary/30" : "hover:bg-muted")}><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-muted text-primary"><QrCode className="h-5 w-5" /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-bold">{row.customer_name}</span><span className="mt-1 block truncate text-xs text-muted-foreground">{row.invoice_number} · <StatusBadge status={row.collection?.payment_status || row.state} /></span></span><span className="text-right"><span className="block font-num text-sm font-bold">{formatINR(row.amount_paise)}</span><ChevronRight className="ml-auto mt-1 h-4 w-4 text-muted-foreground" /></span></button>)}</div>
      </section>
    </div>
    {fullscreen && current?.collection && <div role="dialog" aria-modal="true" aria-label="Full screen payment QR" className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-background p-5"><button onClick={() => setFullscreen(false)} aria-label="Close full screen" className="absolute right-5 top-5 grid h-12 w-12 place-items-center rounded-full border border-border"><X /></button><p className="text-sm font-semibold text-muted-foreground">{current.customer_name} · {current.invoice_number}</p><p className="mt-2 font-num text-4xl font-bold">{formatINR(current.amount_paise)}</p><div className="mt-6 w-full max-w-md rounded-3xl bg-white p-5 shadow-xl"><img src={current.collection.image_url} alt={"Payment QR for " + formatINR(current.amount_paise)} className="w-full" /></div><p className="mt-5 text-sm text-muted-foreground">Expires {formatDateTime(live.data?.close_by ?? current.collection.close_by)}</p><p className="mt-2 text-xs text-muted-foreground">Waiting for Razorpay confirmation</p></div>}
  </div>;
}
