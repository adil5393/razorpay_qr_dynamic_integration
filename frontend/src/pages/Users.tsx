import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Loader2, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";
import { useAuth } from "@/context/AuthContext";
import { api, formatApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { User } from "@/types";

function CreateUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post("/users", form);
      toast.success("Cashier account created");
      setForm({ name: "", email: "", password: "" });
      onOpenChange(false);
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="create-user-dialog">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Add cashier</DialogTitle>
            <DialogDescription>Share the email and password with the cashier privately.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2"><Label>Full name</Label>
            <Input required className="h-12" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="create-user-name-input" /></div>
          <div className="space-y-2"><Label>Email</Label>
            <Input required type="email" className="h-12" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="create-user-email-input" /></div>
          <div className="space-y-2"><Label>Temporary password (min 8 characters)</Label>
            <Input required minLength={8} type="password" className="h-12" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="create-user-password-input" /></div>
          {error && <p data-testid="create-user-error" className="text-sm text-rose-500">{error}</p>}
          <DialogFooter>
            <Button type="submit" className="h-12 w-full sm:w-auto" disabled={busy} data-testid="create-user-submit-button">
              {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Create cashier
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: User | null; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;
    setBusy(true);
    setError("");
    try {
      await api.post(`/users/${user.id}/reset-password`, { new_password: password });
      toast.success(`Password reset for ${user.name}. They have been signed out.`);
      setPassword("");
      onClose();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={!!user} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent data-testid="reset-password-dialog">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Reset password</DialogTitle>
            <DialogDescription>Set a new password for {user?.name}. Existing sessions will be signed out.</DialogDescription>
          </DialogHeader>
          <Input required minLength={8} type="password" className="h-12" placeholder="New password" value={password}
            onChange={(e) => setPassword(e.target.value)} data-testid="reset-password-input" />
          {error && <p data-testid="reset-password-error" className="text-sm text-rose-500">{error}</p>}
          <DialogFooter>
            <Button type="submit" className="h-12" disabled={busy} data-testid="reset-password-submit-button">Reset password</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function Users() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const [filter, setFilter] = useState("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [resetUser, setResetUser] = useState<User | null>(null);
  const [toggleUser, setToggleUser] = useState<User | null>(null);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["users", filter],
    queryFn: async () => (await api.get<User[]>("/users", { params: { status: filter } })).data,
    staleTime: 0,
  });

  const confirmToggle = async () => {
    if (!toggleUser) return;
    try {
      await api.patch(`/users/${toggleUser.id}`, { is_active: !toggleUser.is_active });
      toast.success(toggleUser.is_active ? `${toggleUser.name} deactivated` : `${toggleUser.name} reactivated`);
      qc.invalidateQueries({ queryKey: ["users"] });
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setToggleUser(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Users</h1>
          <p className="mt-1 text-sm text-muted-foreground">Create cashier accounts, deactivate access and reset passwords.</p>
        </div>
        <Button className="h-12 gap-2 px-5" onClick={() => setCreateOpen(true)} data-testid="add-cashier-button"><UserPlus className="h-5 w-5" />Add cashier</Button>
      </div>
      <Tabs value={filter} onValueChange={setFilter}>
        <TabsList className="h-12">
          <TabsTrigger value="all" className="h-10 px-5" data-testid="users-filter-all">All</TabsTrigger>
          <TabsTrigger value="active" className="h-10 px-5" data-testid="users-filter-active">Active</TabsTrigger>
          <TabsTrigger value="inactive" className="h-10 px-5" data-testid="users-filter-inactive">Inactive</TabsTrigger>
        </TabsList>
      </Tabs>
      <div className="rounded-2xl border border-border bg-card">
        {isLoading ? <LoadingState /> : error ? <ErrorState message={formatApiError(error)} onRetry={() => refetch()} /> :
          !data || data.length === 0 ? <EmptyState title="No users in this list" /> : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="users-table">
                <thead className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <tr><th className="px-5 py-3">Name</th><th className="px-5 py-3">Role</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Last login</th><th className="px-5 py-3 text-right">Actions</th></tr>
                </thead>
                <tbody>
                  {data.map((u) => (
                    <tr key={u.id} className="border-t border-border" data-testid={`user-row-${u.id}`}>
                      <td className="px-5 py-4"><p className="font-medium">{u.name}</p><p className="text-xs text-muted-foreground">{u.email}</p></td>
                      <td className="px-5 py-4 capitalize">{u.role}</td>
                      <td className="px-5 py-4"><StatusBadge status={u.is_active ? "active" : "inactive"} testId={`user-status-${u.id}`} /></td>
                      <td className="px-5 py-4 font-num text-muted-foreground">{formatDateTime(u.last_login_at)}</td>
                      <td className="px-5 py-4">
                        <div className="flex justify-end gap-2">
                          <Button variant="outline" className="h-11 gap-1" onClick={() => setResetUser(u)} data-testid={`reset-password-button-${u.id}`}>
                            <KeyRound className="h-4 w-4" />Reset
                          </Button>
                          {me && me.id !== u.id && (
                            <Button variant={u.is_active ? "destructive" : "secondary"} className="h-11" onClick={() => setToggleUser(u)} data-testid={`toggle-active-button-${u.id}`}>
                              {u.is_active ? "Deactivate" : "Activate"}
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </div>
      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />
      <ResetPasswordDialog user={resetUser} onClose={() => setResetUser(null)} />
      <AlertDialog open={!!toggleUser} onOpenChange={(v) => { if (!v) setToggleUser(null); }}>
        <AlertDialogContent data-testid="toggle-active-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>{toggleUser?.is_active ? "Deactivate" : "Activate"} {toggleUser?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              {toggleUser?.is_active ? "They will be signed out immediately and cannot log in until reactivated. Their past collections stay in history." : "They will be able to sign in again."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="h-11" data-testid="toggle-active-cancel">Cancel</AlertDialogCancel>
            <AlertDialogAction className="h-11" onClick={confirmToggle} data-testid="toggle-active-confirm">Confirm</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
