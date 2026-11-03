import { useEffect, useRef, useState } from "react";
import { Loader2, Plus, QrCode } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { QRDisplay } from "@/components/QRDisplay";
import { TestModeBanner } from "@/components/TestModeBanner";
import { useAppConfig, useCollectionStatus } from "@/hooks/queries";
import { api, formatApiError } from "@/lib/api";
import { formatINR } from "@/lib/format";
import type { Collection } from "@/types";

const PRESETS = [100, 500, 1000, 2000, 5000];
const AMOUNT_RE = /^\d{0,7}(\.\d{0,2})?$/;

export default function NewCollection() {
  const qc = useQueryClient();
  const { data: config } = useAppConfig();
  const [amount, setAmount] = useState("");
  const [reference, setReference] = useState("");
  const [customer, setCustomer] = useState("");
  const [description, setDescription] = useState("Payment at billing counter");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [collection, setCollection] = useState<Collection | null>(null);
  const { data: live } = useCollectionStatus(collection?.id);
  const notified = useRef<number | null>(null);

  useEffect(() => {
    if (collection && live?.payment_status === "paid" && notified.current !== collection.id) {
      notified.current = collection.id;
      toast.success(`Payment of ${formatINR(collection.amount_paise)} confirmed by Razorpay`);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    }
  }, [live, collection, qc]);

  const amountNum = Number(amount);
  const valid = amount !== "" && amountNum >= 1 && description.trim().length > 0;

  const onGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    setError("");
    try {
      const { data } = await api.post<Collection>("/collections", {
        amount, reference: reference || null, customer_name: customer || null, description,
      });
      setCollection(data);
      toast.success("QR generated");
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setCollection(null);
    setAmount("");
    setReference("");
    setCustomer("");
    setError("");
  };

  return (
    <div className="space-y-6">
      <TestModeBanner />
      <div className="grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <form onSubmit={onGenerate} className="space-y-6 rounded-2xl border border-border bg-card p-6 sm:p-8" data-testid="qr-form">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">New QR collection</h1>
            <p className="mt-1 text-sm text-muted-foreground">Fixed-amount, single-use UPI QR. Closes after {config?.qr_expiry_minutes ?? 30} minutes if unpaid.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="amount">Amount (INR)</Label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 font-num text-2xl text-muted-foreground">₹</span>
              <Input id="amount" inputMode="decimal" placeholder="0.00" value={amount} disabled={!!collection}
                onChange={(e) => { if (AMOUNT_RE.test(e.target.value)) setAmount(e.target.value); }}
                className="h-16 pl-10 font-num text-3xl font-bold" data-testid="qr-amount-input" />
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {PRESETS.map((p) => (
                <Button key={p} type="button" variant="outline" disabled={!!collection} className="h-12 min-w-[84px] font-num"
                  onClick={() => setAmount(String(p))} data-testid={`preset-amount-${p}-button`}>₹{p.toLocaleString("en-IN")}</Button>
              ))}
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="ref">Invoice / reference <span className="text-muted-foreground">(optional)</span></Label>
              <Input id="ref" maxLength={40} value={reference} disabled={!!collection} onChange={(e) => setReference(e.target.value)}
                className="h-12 font-num" placeholder="INV-1024" data-testid="qr-reference-input" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cust">Customer name <span className="text-muted-foreground">(optional)</span></Label>
              <Input id="cust" maxLength={120} value={customer} disabled={!!collection} onChange={(e) => setCustomer(e.target.value)}
                className="h-12" data-testid="qr-customer-name-input" />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="desc">Description</Label>
            <Input id="desc" maxLength={255} value={description} disabled={!!collection} onChange={(e) => setDescription(e.target.value)}
              className="h-12" data-testid="qr-description-input" />
          </div>
          {error && <p data-testid="qr-form-error" className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
          {collection ? (
            <Button type="button" onClick={reset} className="h-16 w-full gap-2 text-lg" data-testid="new-collection-button">
              <Plus className="h-5 w-5" /> Start a new collection
            </Button>
          ) : (
            <Button type="submit" disabled={!valid || busy || config?.razorpay_configured === false} className="h-16 w-full gap-2 text-lg" data-testid="generate-qr-button">
              {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <QrCode className="h-5 w-5" />}
              {busy ? "Creating QR with Razorpay…" : `Generate QR${valid ? ` for ${formatINR(Math.round(amountNum * 100))}` : ""}`}
            </Button>
          )}
        </form>

        <section className="rounded-2xl border border-border bg-card p-6 sm:p-8" data-testid="qr-panel">
          {collection ? (
            <QRDisplay collection={collection} live={live} />
          ) : (
            <div className="flex h-full min-h-[420px] flex-col items-center justify-center gap-4 text-center">
              <div className="grid h-40 w-40 place-items-center rounded-3xl border-2 border-dashed border-border">
                <QrCode className="h-16 w-16 text-muted-foreground/50" />
              </div>
              <p className="font-display text-lg font-medium">The QR will appear here</p>
              <p className="max-w-xs text-sm text-muted-foreground">Enter the amount and tap Generate. Turn the screen towards the customer to scan.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
