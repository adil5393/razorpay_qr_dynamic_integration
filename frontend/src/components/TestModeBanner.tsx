import { AlertTriangle, KeyRound } from "lucide-react";
import { useAppConfig } from "@/hooks/queries";

export function TestModeBanner() {
  const { data } = useAppConfig();
  if (!data) return null;
  if (!data.razorpay_configured) {
    return (
      <div data-testid="razorpay-not-configured-banner" className="flex items-start gap-3 rounded-r-lg border-l-4 border-rose-500 bg-rose-500/10 p-4 text-sm font-medium text-rose-700 dark:text-rose-300">
        <KeyRound className="mt-0.5 h-5 w-5 shrink-0" />
        <span>Razorpay is not connected yet. QR codes cannot be generated until an administrator adds the API keys.</span>
      </div>
    );
  }
  if (data.razorpay_mode !== "test") return null;
  return (
    <div data-testid="test-mode-banner" className="flex items-start gap-3 rounded-r-lg border-l-4 border-amber-500 bg-amber-500/10 p-4 text-sm font-medium text-amber-800 shadow-sm dark:text-amber-300">
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
      <span>
        <strong>Razorpay Test Mode.</strong> Test-mode QR codes are not meant for real UPI scanning and no real money moves.
        To simulate a payment, open the QR in your Razorpay test dashboard. Switch to live keys to collect real payments.
      </span>
    </div>
  );
}
