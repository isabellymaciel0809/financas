import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

const POLL_MS = 2000;
// O job começa logo depois da resposta da importação; esta janela cobre a corrida entre a
// resposta chegar e o job aparecer como "rodando".
const WATCH_WINDOW_MS = 15000;

/** Acompanha a categorização por IA em segundo plano e atualiza as telas quando ela termina. */
export function useCategorizationJob(onFinish: (categorized: number, error: string | null) => void) {
  const queryClient = useQueryClient();
  const [watchUntil, setWatchUntil] = useState(0);
  const sawRunning = useRef(false);

  const status = useQuery({
    queryKey: ["categorize-status"],
    queryFn: api.categorizationStatus,
    refetchInterval: (query) =>
      query.state.data?.running || Date.now() < watchUntil ? POLL_MS : false,
  });

  useEffect(() => {
    const data = status.data;
    if (!data) return;
    if (data.running) {
      sawRunning.current = true;
      return;
    }
    const refresh = () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["summary"] });
    };
    if (sawRunning.current) {
      sawRunning.current = false;
      setWatchUntil(0);
      refresh();
      onFinish(data.last_categorized, data.last_error);
    } else if (watchUntil && Date.now() >= watchUntil) {
      setWatchUntil(0);
      refresh(); // terminou rápido demais para vermos "rodando"
    }
  }, [status.data, watchUntil, queryClient, onFinish]);

  /** Chamado pelas telas quando enfileiram transações para a IA. */
  const { refetch } = status;
  const watch = useCallback(
    (queued: number) => {
      if (queued <= 0) return;
      setWatchUntil(Date.now() + WATCH_WINDOW_MS);
      refetch();
    },
    [refetch],
  );

  return { running: status.data?.running ?? false, pending: status.data?.pending ?? 0, watch };
}
