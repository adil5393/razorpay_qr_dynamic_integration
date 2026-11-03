import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LoadingState } from "@/components/States";

export function ProtectedRoute({ adminOnly }: { adminOnly?: boolean }) {
  const { user } = useAuth();
  if (user === null) return <LoadingState label="Checking your session…" />;
  if (user === false) return <Navigate to="/login" replace />;
  if (adminOnly && user.role !== "admin") return <Navigate to="/" replace />;
  return <Outlet />;
}
