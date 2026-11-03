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
import Settings from "@/pages/Settings";
import Users from "@/pages/Users";

function ThemedToaster() {
  const { theme } = useTheme();
  return <Toaster theme={theme} position="top-right" richColors />;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route index element={<Dashboard />} />
                <Route path="collect" element={<NewCollection />} />
                <Route path="history" element={<History />} />
                <Route path="collections/:id" element={<CollectionDetail />} />
                <Route element={<ProtectedRoute adminOnly />}>
                  <Route path="users" element={<Users />} />
                  <Route path="settings" element={<Settings />} />
                </Route>
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
        <ThemedToaster />
      </AuthProvider>
    </ThemeProvider>
  );
}
