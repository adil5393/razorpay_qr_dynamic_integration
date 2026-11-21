import { useLayoutEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { History, LayoutDashboard, ListOrdered, LogOut, Menu, Moon, QrCode, Settings2, Sun, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useAuth } from "@/context/AuthContext";
import { useAppConfig } from "@/hooks/queries";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard-link", admin: false },
  { to: "/collect", label: "New QR Collection", icon: QrCode, testId: "nav-new-qr-link", admin: false },
  { to: "/history", label: "QR History", icon: History, testId: "nav-qr-history-link", admin: false },
  { to: "/users", label: "Users", icon: Users, testId: "nav-user-mgmt-link", admin: true },
  { to: "/terminal", label: "Odoo requests", icon: QrCode, testId: "nav-odoo-requests", admin: true },
  { to: "/odoo-deliveries", label: "Odoo sync", icon: History, testId: "nav-odoo-sync", admin: true },
  { to: "/settings", label: "Razorpay Setup", icon: Settings2, testId: "nav-settings-link", admin: true },
];

function Brand() {
  return (
    <div className="flex items-center gap-3 px-5 py-6">
      <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary text-primary-foreground"><QrCode className="h-5 w-5" /></div>
      <div className="leading-tight">
        <p className="font-display text-base font-bold tracking-tight">Universal QR</p>
        <p className="text-xs text-muted-foreground">Collections</p>
      </div>
    </div>
  );
}

function NavItems({ onNavigate, prefix }: { onNavigate?: () => void; prefix: string }) {
  const { user } = useAuth();
  const isAdmin = user && user.role === "admin";
  const config = useAppConfig();
  const terminal = !isAdmin && config.data?.odoo_terminal_cutover;
  return (
    <nav className="flex flex-col gap-1 px-3">
      {NAV.filter((n) => (!n.admin || isAdmin) && !(terminal && n.to === "/collect")).map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={n.to === "/"}
          onClick={onNavigate}
          data-testid={`${prefix}${n.testId}`}
          className={({ isActive }) => cn(
            "flex min-h-[48px] items-center gap-3 rounded-lg px-4 text-sm font-medium transition-colors",
            isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          <n.icon className="h-5 w-5" />{terminal && n.to === "/" ? "Terminal" : n.label}
        </NavLink>
      ))}
    </nav>
  );
}

function UserFooter() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return (
    <div className="mt-auto border-t border-border p-4">
      <p className="truncate text-sm font-medium" data-testid="sidebar-user-name">{user.name}</p>
      <p className="truncate text-xs text-muted-foreground">{user.email}</p>
      <Button variant="ghost" className="mt-3 h-11 w-full justify-start gap-2" onClick={logout} data-testid="logout-button">
        <LogOut className="h-4 w-4" /> Sign out
      </Button>
    </div>
  );
}

export default function AppLayout() {
  const [open, setOpen] = useState(false);
  const [queueCount, setQueueCount] = useState(0);
  useLayoutEffect(() => {
    const onCount = (event: Event) => setQueueCount((event as CustomEvent<number>).detail);
    window.addEventListener("uqc:queue-count", onCount);
    return () => window.removeEventListener("uqc:queue-count", onCount);
  }, []);
  const { user } = useAuth();
  const config = useAppConfig();
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const cashierTerminal = !!user && user.role === "cashier" && !!config.data?.odoo_terminal_cutover;
  const legacyCashier = !!user && user.role === "cashier" && !config.data?.odoo_terminal_cutover;
  const terminalPath = cashierTerminal ? "/" : "/terminal";
  const inTerminal = location.pathname === terminalPath;
  const queueView = new URLSearchParams(location.search).get("view") === "queue";
  const current = NAV.find((n) => (n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to)));

  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-border bg-card lg:flex">
        <Brand />
        <NavItems prefix="" />
        <UserFooter />
      </aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="flex w-72 flex-col p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Brand />
          <NavItems prefix="mobile-" onNavigate={() => setOpen(false)} />
          <UserFooter />
        </SheetContent>
      </Sheet>
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur-md sm:px-8">
          <Button variant="ghost" size="icon" className="h-11 w-11 lg:hidden" onClick={() => setOpen(true)} data-testid="mobile-menu-button">
            <Menu className="h-5 w-5" />
          </Button>
          <div className="leading-tight"><p className="font-display text-base font-bold tracking-tight lg:hidden">UniversalQR</p><p className="hidden font-display text-base font-semibold tracking-tight lg:block">{current?.label || "Collection details"}</p><p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground lg:hidden">Payment terminal</p></div>
          <div className="ml-auto flex items-center gap-3">
            {user && (
              <span data-testid="user-role-badge" className={cn(
                "rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider",
                user.role === "admin" ? "border-primary/40 bg-primary/10 text-primary" : "border-border bg-muted text-muted-foreground",
              )}>{user.role}</span>
            )}
            <Button variant="outline" size="icon" className="h-11 w-11" onClick={toggle} data-testid="theme-toggle-button" aria-label="Toggle theme">
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 pb-28 pt-6 sm:px-8 sm:pt-10 lg:pb-10">
          <Outlet />
        </main>
      </div>
      <nav aria-label="Mobile navigation" className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-3 border-t border-border bg-card/95 pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_25px_rgba(0,0,0,0.05)] backdrop-blur lg:hidden">
        {legacyCashier ? <>
          <NavLink to="/" end className={({ isActive }) => cn("flex min-h-[66px] flex-col items-center justify-center gap-1 text-xs font-semibold", isActive ? "text-primary" : "text-muted-foreground")}><LayoutDashboard className="h-5 w-5" />Dashboard</NavLink>
          <NavLink to="/collect" className={({ isActive }) => cn("flex min-h-[66px] flex-col items-center justify-center gap-1 text-xs font-semibold", isActive ? "text-primary" : "text-muted-foreground")}><QrCode className="h-5 w-5" />New QR</NavLink>
        </> : <>
          <NavLink to={terminalPath} end className={cn("flex min-h-[66px] flex-col items-center justify-center gap-1 text-xs font-semibold", inTerminal && !queueView ? "text-primary" : "text-muted-foreground")}><QrCode className="h-5 w-5" />Terminal</NavLink>
          <NavLink to={terminalPath + "?view=queue"} className={cn("relative flex min-h-[66px] flex-col items-center justify-center gap-1 text-xs font-semibold", inTerminal && queueView ? "text-primary" : "text-muted-foreground")}><span className="relative"><ListOrdered className="h-5 w-5" />{queueCount > 0 && <span className="absolute -right-3 -top-2 rounded-full bg-primary px-1 text-[10px] leading-4 text-primary-foreground">{queueCount}</span>}</span>Queue</NavLink>
        </>}
        <NavLink to="/history" className={({ isActive }) => cn("flex min-h-[66px] flex-col items-center justify-center gap-1 text-xs font-semibold", isActive ? "text-primary" : "text-muted-foreground")}><History className="h-5 w-5" />History</NavLink>
      </nav>
    </div>
  );
}
