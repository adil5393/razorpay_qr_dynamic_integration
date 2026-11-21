import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import "@/App.css";
import AppLayout from "@/components/AppLayout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AuthProvider } from "@/context/AuthContext";
import { ThemeProvider, useTheme } from "@/context/ThemeContext";
import CollectionDetail from "@/pages/CollectionDetail";
import Dashboard from "@/pages/Dashboard";
import History from "@/pages/History";
import Login from "@/pages/Login";
import NewCollection from "@/pages/NewCollection";
import PublicPay from "@/pages/PublicPay";
import Settings from "@/pages/Settings";
import Users from "@/pages/Users";
import Terminal from "@/pages/Terminal";
import Deliveries from "@/pages/Deliveries";
import { useAuth } from "@/context/AuthContext";
import { useAppConfig } from "@/hooks/queries";
import { LoadingState } from "@/components/States";

function Home() {
  const { user } = useAuth();
  const config = useAppConfig();
  if (config.isLoading) return <LoadingState />;
  if (config.error) return <p>Unable to load configuration.</p>;
  return user && user.role === "cashier" && config.data?.odoo_terminal_cutover ? <Terminal /> : <Dashboard />;
}

function CollectRoute() {
  const { user } = useAuth();
  const config = useAppConfig();
  if (config.isLoading) return <LoadingState />;
  if (config.error || (user && user.role !== "admin" && config.data?.odoo_terminal_cutover)) return <Navigate to="/" replace />;
  return <NewCollection />;
}

function ThemedToaster() {
  const { theme } = useTheme();
  return <Toaster theme={theme} position="top-right" richColors />;
}

/** Staff app: everything behind login. */
function StaffApp() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route index element={<Home />} />
            <Route path="collect" element={<CollectRoute />} />
            <Route path="history" element={<History />} />
            <Route path="terminal" element={<Terminal />} />
            <Route path="collections/:id" element={<CollectionDetail />} />
            <Route element={<ProtectedRoute adminOnly />}>
              <Route path="users" element={<Users />} />
              <Route path="settings" element={<Settings />} />
              <Route path="odoo-deliveries" element={<Deliveries />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <ThemedToaster />
    </AuthProvider>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          {/* Customer payment page: public, outside the staff session (no auth calls, no cookies). */}
          <Route path="/pay/:token" element={<PublicPay />} />
          <Route path="/*" element={<StaffApp />} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
