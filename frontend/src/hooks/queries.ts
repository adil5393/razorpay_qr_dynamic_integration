import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AppConfig, CollectionStatus } from "@/types";

export function useAppConfig() {
  return useQuery({
    queryKey: ["app-config"],
    queryFn: async () => (await api.get<AppConfig>("/config")).data,
    staleTime: 5 * 60_000,
  });
}

export function useCollectionStatus(id: number | undefined) {
  return useQuery({
    queryKey: ["collection-status", id],
    queryFn: async () =>
      (await api.get<CollectionStatus>(`/collections/${id}/status`, { params: { refresh: true } })).data,
    enabled: !!id,
    staleTime: 0,
    refetchInterval: (q) => {
      const d = q.state.data as CollectionStatus | undefined;
      return !d || d.payment_status === "pending" ? 5000 : false;
    },
  });
}
