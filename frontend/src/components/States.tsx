import React from "react";
import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div data-testid="loading-state" className="flex items-center justify-center gap-3 py-16 text-muted-foreground">
      <Loader2 className="h-5 w-5 animate-spin" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div data-testid="empty-state" className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="rounded-2xl bg-muted p-4"><Inbox className="h-7 w-7 text-muted-foreground" /></div>
      <p className="font-display text-lg font-medium">{title}</p>
      {hint && <p className="max-w-sm text-sm text-muted-foreground">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div data-testid="error-state" className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <div className="rounded-2xl bg-rose-500/10 p-4"><AlertCircle className="h-7 w-7 text-rose-500" /></div>
      <p className="max-w-md text-sm text-muted-foreground">{message}</p>
      {onRetry && <Button variant="outline" onClick={onRetry} data-testid="error-retry-button">Try again</Button>}
    </div>
  );
}
