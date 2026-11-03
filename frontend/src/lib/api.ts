import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

export const API_BASE = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API_BASE, withCredentials: true });

let refreshing: Promise<unknown> | null = null;

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    const url = original?.url || "";
    if (error.response?.status === 401 && original && !original._retry && !url.includes("/auth/")) {
      original._retry = true;
      try {
        refreshing = refreshing || api.post("/auth/refresh").finally(() => { refreshing = null; });
        await refreshing;
        return api(original);
      } catch {
        window.dispatchEvent(new Event("uqc:session-expired"));
      }
    }
    return Promise.reject(error);
  },
);

export function formatApiError(err: unknown): string {
  const e = err as AxiosError<{ detail?: unknown }>;
  const detail = e?.response?.data?.detail;
  if (detail == null) {
    if (e?.response?.status) return `Request failed (${e.response.status}). Please try again.`;
    return e?.message ? "Network error. Check your connection and try again." : "Something went wrong.";
  }
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => (d && typeof d.msg === "string" ? d.msg.replace(/^Value error, /, "") : JSON.stringify(d)))
      .join(" ");
  }
  return String(detail);
}
