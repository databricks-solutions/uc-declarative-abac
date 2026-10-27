import {
  useExplainSuspense,
  type ChainGraphNodeOut,
  type ChainGraphOut,
} from "@/lib/api";
import { CircleCheck } from "lucide-react";
import { ChainGraph, ChainGraphSteps } from "./chain-graph";

export function RowFilterFlow({
  principal,
  table,
  mode = "graph",
  selectedNodeId,
  onNodeActivate,
  onGraphChange,
  showExemption = true,
  focusColumn,
}: {
  principal: string;
  table: string;
  mode?: "graph" | "steps";
  selectedNodeId?: string;
  onNodeActivate?: (node: ChainGraphNodeOut) => void;
  onGraphChange?: (graph: ChainGraphOut) => void;
  showExemption?: boolean;
  /** Show only the filter flow through this column of the table. */
  focusColumn?: string;
}) {
  const { data } = useExplainSuspense({ params: { principal, table } });
  const exceptedBy = data.data.row_filter_excepted_by;
  const props = {
    principal,
    table,
    hideColumnMasks: true,
    hideGrants: true,
    focusColumn,
  };

  return (
    <div className="space-y-3">
      {showExemption && exceptedBy && (
        <div
          data-filter-exemption
          className="flex items-start gap-2 rounded-md border border-emerald-300 bg-emerald-100 p-3 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
        >
          <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="space-y-0.5 text-xs">
            <p className="font-semibold">Exempt from row filtering</p>
            <p>
              <span className="font-mono">{principal}</span> is exempt via{" "}
              <span className="font-mono">{exceptedBy}</span>. The row-filter
              policy does not apply, so all rows remain visible.
            </p>
          </div>
        </div>
      )}
      {mode === "graph" ? (
        <ChainGraph
          {...props}
          selectedNodeId={selectedNodeId}
          onNodeActivate={onNodeActivate}
          hideDirectColumnEdges
          onGraphChange={onGraphChange}
        />
      ) : (
        <ChainGraphSteps
          {...props}
          hideDirectColumnEdges
          onGraphChange={onGraphChange}
        />
      )}
    </div>
  );
}
