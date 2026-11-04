import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { AlertTriangle, Ban, CheckCircle2, Clock, Loader2, ShieldCheck, Timer, WifiOff } from "lucide-react";
import { publicApi } from "@/lib/publicApi";
import { formatDateTime, formatINR } from "@/lib/format";
import type { PublicPayment } from "@/types";

const MIN_POLL_MS = 3000;
const MAX_POLL_MS = 5000;
// After the QR's expiry time, keep checking this long for a last-moment payment, then stop.
const POST_EXPIRY_GRACE_MS = 10 * 60_000;
const TOKEN_RE = /^[A-Za-z0-9_-]{43}$/;

class NotFound extends Error {}

/** Server time minus local time, so the countdown is right even if the phone's clock is off. */
function useServerClock(data: PublicPayment | undefined, fetchedAt: number) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const offset = data ? new Date(data.server_time).getTime() - fetchedAt : 0;
  return now + offset;
}

function formatCountdown(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export default function PublicPay() {
  const { token = "" } = useParams();
  const validToken = TOKEN_RE.test(token);

  const { data, error, isLoading, isError, dataUpdatedAt, isFetching } = useQuery({
    queryKey: ["public-pay", token],
    enabled: validToken,
    queryFn: async () => {
      try {
        return (await publicApi.get<PublicPayment>(`/pay/${token}`)).data;
      } catch (e) {
        if (axios.isAxiosError(e) && e.response?.status === 404) throw new NotFound();
        throw e;
      }
    },
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: (count, e) => !(e instanceof NotFound) && count < 3,
    refetchInterval: (q) => {
      const d = q.state.data as PublicPayment | undefined;
      if (q.state.error instanceof NotFound) return false;
      if (!d) return MAX_POLL_MS; // transient error before first load: keep trying
      if (d.status !== "pending" || d.poll_interval_ms == null) return false; // terminal: stop polling
      if (d.expires_at && Date.now() - new Date(d.expires_at).getTime() > POST_EXPIRY_GRACE_MS) return false;
      return Math.min(MAX_POLL_MS, Math.max(MIN_POLL_MS, d.poll_interval_ms));
    },
  });

  const serverNow = useServerClock(data, dataUpdatedAt);

  useEffect(() => {
    document.title = data?.status === "paid" ? "Payment successful" : "Pay with UPI";
  }, [data?.status]);

  if (!validToken || error instanceof NotFound) {
    return (
      <Shell>
        <StateBlock icon={<AlertTriangle className="h-10 w-10 text-amber-500" />} title="Payment link not found"
          body="This link is not valid. Please check it, or ask the merchant to send it again." testId="public-not-found" />
      </Shell>
    );
  }
  if (isLoading) {
    return (
      <Shell>
        <div className="flex items-center justify-center gap-3 py-24 text-muted-foreground" data-testid="public-loading">
          <Loader2 className="h-6 w-6 animate-spin" /> Loading payment…
        </div>
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell>
        <StateBlock icon={<WifiOff className="h-10 w-10 text-muted-foreground" />} title="Can't reach the server"
          body="Check your internet connection. We'll keep trying." testId="public-offline" />
      </Shell>
    );
  }

  const msLeft = data.expires_at ? new Date(data.expires_at).getTime() - serverNow : null;
  const pastExpiry = msLeft !== null && msLeft <= 0;
  const stoppedChecking = data.status === "pending" && data.expires_at
    && Date.now() - new Date(data.expires_at).getTime() > POST_EXPIRY_GRACE_MS;

  return (
    <Shell testMode={data.test_mode}>
      <div className="text-center">
        <p className="text-sm text-muted-foreground">{data.customer_name ? "Payment request for" : "Payment request"}</p>
        {data.customer_name && (
          <p data-testid="public-customer-name" className="mt-0.5 break-words font-display text-xl font-semibold">{data.customer_name}</p>
        )}
        <p data-testid="public-amount" className="mt-3 font-num text-4xl font-bold tracking-tight sm:text-5xl">
          {formatINR(data.amount_paise)}
        </p>
      </div>

      <div aria-live="polite" className="mt-6">
        {data.status === "paid" && (
          <StateBlock tone="success" testId="public-paid" icon={<CheckCircle2 className="h-16 w-16" />} title="Payment successful"
            body={<>
              Confirmed by Razorpay{data.paid_at ? ` on ${formatDateTime(data.paid_at)}` : ""}.
              {data.payment_reference && <span className="mt-2 block font-num text-xs opacity-80">Ref: {data.payment_reference}</span>}
            </>} />
        )}
        {data.status === "expired" && (
          <StateBlock testId="public-expired" icon={<Clock className="h-12 w-12 text-rose-500" />} title="This QR has expired"
            body="No payment was received in time. Please ask the merchant for a new QR." />
        )}
        {data.status === "cancelled" && (
          <StateBlock testId="public-cancelled" icon={<Ban className="h-12 w-12 text-muted-foreground" />} title="Payment request cancelled"
            body="This QR was cancelled by the merchant and can no longer be paid." />
        )}
        {data.status === "pending" && data.confirming && (
          <StateBlock testId="public-confirming" icon={<Loader2 className="h-12 w-12 animate-spin text-primary" />}
            title="Confirming your payment…" body="Razorpay has received a payment. Please wait while it is confirmed." />
        )}
        {data.status === "pending" && !data.confirming && pastExpiry && (
          <StateBlock testId="public-expiring" icon={<Clock className="h-12 w-12 text-amber-500" />} title="QR time is up"
            body={stoppedChecking
              ? "No payment was confirmed. If you paid, show this screen to the merchant; otherwise ask for a new QR."
              : "Checking for any last-moment payment…"} />
        )}
        {data.status === "pending" && !data.confirming && !pastExpiry && data.qr_image_url && (
          <div className="flex flex-col items-center gap-4" data-testid="public-qr-block">
            <div className="w-full max-w-[18rem] rounded-2xl border border-border bg-white p-3 shadow-sm sm:max-w-xs">
              <img data-testid="public-qr-image" src={data.qr_image_url} referrerPolicy="no-referrer"
                alt={`UPI QR code to pay ${formatINR(data.amount_paise)}`} className="aspect-square h-auto w-full object-contain" />
            </div>
            <p className="text-center text-sm text-muted-foreground">Scan with any UPI app (GPay, PhonePe, Paytm, BHIM…)</p>
            {msLeft !== null && (
              <p data-testid="public-countdown" className="flex items-center gap-2 font-num text-lg font-semibold" aria-label="Time left to pay">
                <Timer className="h-5 w-5" /> {formatCountdown(msLeft)}
              </p>
            )}
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} /> Waiting for payment — this page updates automatically
            </p>
          </div>
        )}
        {isError && data.status === "pending" && (
          <p className="mt-4 flex items-center justify-center gap-2 text-xs text-amber-600" data-testid="public-reconnecting">
            <WifiOff className="h-3.5 w-3.5" /> Connection problem — retrying…
          </p>
        )}
      </div>
    </Shell>
  );
}

function Shell({ children, testMode }: { children: React.ReactNode; testMode?: boolean }) {
  return (
    <div className="min-h-screen bg-muted/40 px-4 py-6 sm:py-12">
      <main className="mx-auto w-full max-w-md">
        <div className="mb-4 flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5 font-medium"><ShieldCheck className="h-4 w-4" /> Secure UPI payment via Razorpay</span>
          {testMode && (
            <span data-testid="public-test-mode" className="rounded-full border border-amber-400 bg-amber-100 px-2 py-0.5 font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-300">
              TEST MODE
            </span>
          )}
        </div>
        <div className="rounded-3xl border border-border bg-card p-6 shadow-sm sm:p-8">{children}</div>
        <p className="mt-4 text-center text-xs text-muted-foreground">Universal QR Collections</p>
      </main>
    </div>
  );
}

function StateBlock({ icon, title, body, tone, testId }: {
  icon: React.ReactNode; title: string; body: React.ReactNode; tone?: "success"; testId?: string;
}) {
  const success = tone === "success";
  return (
    <div data-testid={testId}
      className={`flex flex-col items-center gap-3 rounded-2xl p-6 text-center ${success ? "bg-emerald-600 text-white" : ""}`}>
      {icon}
      <p className="font-display text-2xl font-bold">{title}</p>
      <div className={`max-w-xs text-sm ${success ? "opacity-95" : "text-muted-foreground"}`}>{body}</div>
    </div>
  );
}
