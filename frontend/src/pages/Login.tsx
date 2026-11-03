import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Loader2, Lock, QrCode } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";
import { formatApiError } from "@/lib/api";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen bg-background text-foreground lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-[#0B1220] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-blue-600/30 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-blue-600"><QrCode className="h-6 w-6" /></div>
          <span className="font-display text-lg font-bold tracking-tight">Universal QR Collections</span>
        </div>
        <div className="relative max-w-md">
          <h1 className="font-display text-4xl font-bold leading-tight tracking-tight xl:text-5xl">Collect UPI payments at the counter, confirmed by Razorpay.</h1>
          <p className="mt-6 text-base text-slate-300">Generate a fixed-amount QR in seconds and watch it turn green only when the payment is captured.</p>
        </div>
        <p className="relative text-xs text-slate-500">Authorized staff only</p>
      </div>
      <div className="flex items-center justify-center p-6 sm:p-12">
        <form onSubmit={onSubmit} className="w-full max-w-sm space-y-6" data-testid="login-form">
          <div>
            <h2 className="font-display text-3xl font-bold tracking-tight">Sign in</h2>
            <p className="mt-2 text-sm text-muted-foreground">Use the account your administrator created for you.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)}
              className="h-12 text-base" data-testid="login-email-input" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" autoComplete="current-password" required value={password}
              onChange={(e) => setPassword(e.target.value)} className="h-12 text-base" data-testid="login-password-input" />
          </div>
          {error && <p data-testid="login-error" className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
          <Button type="submit" className="h-12 w-full text-base" disabled={busy} data-testid="login-submit-button">
            {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <><Lock className="mr-2 h-4 w-4" />Sign in</>}
          </Button>
          <p className="text-center text-xs text-muted-foreground">No self sign-up. Forgot your password? Ask an administrator to reset it.</p>
        </form>
      </div>
    </div>
  );
}
