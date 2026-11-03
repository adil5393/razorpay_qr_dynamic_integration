import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { History, LayoutDashboard, LogOut, Menu, Moon, QrCode, Settings2, Sun, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testId: "nav-dashboard-link", admin: false },
  { to: "/collect", label: "New QR Collection", icon: QrCode, testId: "nav-new-qr-link", admin: false },
  { to: "/history", label: "QR History", icon: History, testId: "nav-qr-history-link", admin: false },
  { to: "/users", label: "Users", icon: Users, testId: "nav-user-mgmt-link", admin: true },
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
  return (
    <nav className="flex flex-col gap-1 px-3">
      {NAV.filter((n) => !n.admin || isAdmin).map((n) => (
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
          <n.icon className="h-5 w-5" />{n.label}
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
  const { user } = useAuth();
  const { theme, toggle } = useTheme();
  const location = useLocation();
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
          <p className="font-display text-base font-semibold tracking-tight">{current?.label || "Collection details"}</p>
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
        <main className="mx-auto max-w-7xl px-4 py-8 sm:px-8 sm:py-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
