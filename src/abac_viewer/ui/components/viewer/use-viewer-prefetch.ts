import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  columnsForPrincipal,
  columnsForPrincipalKey,
  explain,
  explainColumn,
  explainColumnGraph,
  explainColumnGraphKey,
  explainColumnKey,
  explainGraph,
  explainGraphKey,
  explainKey,
} from "@/lib/api";

const PREFETCH_STALE_TIME = 60_000;

export function useViewerPrefetch() {
  const queryClient = useQueryClient();

  const prefetchColumns = useCallback(
    (principal: string, table: string) => {
      const params = { principal, filter: "all" as const, table };
      void queryClient.prefetchQuery({
        queryKey: columnsForPrincipalKey(params),
        queryFn: () => columnsForPrincipal(params),
        staleTime: PREFETCH_STALE_TIME,
      });
    },
    [queryClient],
  );

  const prefetchTableWhy = useCallback(
    (principal: string, table: string) => {
      const explainParams = { principal, table };
      const graphParams = {
        principal,
        table,
        include_column_masks: false,
        include_row_filters: false,
        include_grants: true,
        focus_column: undefined,
      };
      void Promise.all([
        queryClient.prefetchQuery({
          queryKey: explainKey(explainParams),
          queryFn: () => explain(explainParams),
          staleTime: PREFETCH_STALE_TIME,
        }),
        queryClient.prefetchQuery({
          queryKey: explainGraphKey(graphParams),
          queryFn: () => explainGraph(graphParams),
          staleTime: PREFETCH_STALE_TIME,
        }),
      ]);
    },
    [queryClient],
  );

  const prefetchColumnWhy = useCallback(
    (principal: string, column: string) => {
      const columnParams = { principal, column };
      const parts = column.split(".");
      const table = parts.slice(0, -1).join(".");
      const focusColumn = parts.at(-1);
      const filterGraphParams = {
        principal,
        table,
        include_column_masks: false,
        include_row_filters: true,
        include_grants: false,
        focus_column: focusColumn,
      };
      void Promise.all([
        queryClient.prefetchQuery({
          queryKey: explainColumnKey(columnParams),
          queryFn: () => explainColumn(columnParams),
          staleTime: PREFETCH_STALE_TIME,
        }),
        queryClient.prefetchQuery({
          queryKey: explainColumnGraphKey(columnParams),
          queryFn: () => explainColumnGraph(columnParams),
          staleTime: PREFETCH_STALE_TIME,
        }),
        queryClient.prefetchQuery({
          queryKey: explainGraphKey(filterGraphParams),
          queryFn: () => explainGraph(filterGraphParams),
          staleTime: PREFETCH_STALE_TIME,
        }),
      ]);
    },
    [queryClient],
  );

  return { prefetchColumns, prefetchTableWhy, prefetchColumnWhy };
}
