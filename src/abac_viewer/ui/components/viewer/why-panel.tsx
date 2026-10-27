import { Suspense } from "react";
import { ArrowLeft } from "lucide-react";
import { useExplainSuspense } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ModeToggle } from "@/components/apx/mode-toggle";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ChainGraph } from "./chain-graph";
import { GroupedChainDetail } from "./chain-detail";
import { AccessBadge, FilterBadge, MaskBadge } from "./status-badge";
import { useViewerPrefetch } from "./use-viewer-prefetch";
import { useViewerUrlState } from "./viewer-url-state";
import { RowFilterFlow } from "./row-filter-flow";

/** Why-panel: the causal chain for one (principal, table). Every node is a
 * join witness; policy/membership nodes link to the YAML that declared them.
 * Per-column mask detail lives in the dedicated column Why page. */

function WhyContent({
  principal,
  table,
  onColumnWhy,
  showUpstreamCascade,
  onShowUpstreamCascadeChange,
}: {
  principal: string;
  table: string;
  onColumnWhy: (column: string) => void;
  showUpstreamCascade: boolean;
  onShowUpstreamCascadeChange: (show: boolean) => void;
}) {
  const { data } = useExplainSuspense({ params: { principal, table } });
  const v = data.data;
  const grantGroups = v.groups.filter((group) =>
    group.policy.label.startsWith("grant policy"),
  );
  const { prefetchColumnWhy } = useViewerPrefetch();
  const maskedColumns = v.columns.filter((column) => column.masked);

  const columnLink = (column: string) => {
    const columnFullName = `${table}.${column}`;
    return (
      <button
        key={column}
        type="button"
        className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/60"
        onPointerEnter={() => prefetchColumnWhy(principal, columnFullName)}
        onFocus={() => prefetchColumnWhy(principal, columnFullName)}
        onClick={() => onColumnWhy(columnFullName)}
      >
        <span className="font-mono text-xs">{column}</span>
        <span className="ml-auto text-xs text-primary">Why?</span>
      </button>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <AccessBadge canRead={v.can_read} />
        {v.can_read && v.row_filter_targeted && (
          <FilterBadge filtered={v.row_filtered} targeted />
        )}
        {v.can_read && maskedColumns.length > 0 && <MaskBadge masked />}
      </div>
      <p className="text-sm leading-relaxed">
        {v.can_read
          ? `${principal} can read ${table} through the declared grant path below.`
          : `${principal} cannot read ${table}.`}
      </p>
      {!v.can_read && (
        <p className="text-xs text-muted-foreground">
          Missing prerequisites: {v.missing.join(", ")}. (Why-not diagnosis is
          out of scope for v1 — this lists the unmet privileges only.)
        </p>
      )}
      <div
        className="sticky left-0 flex gap-3"
        style={{ width: "calc(100vw - 4rem)" }}
      >
        <div className="min-w-0 flex-1 basis-0 space-y-2">
          <h4 className="text-sm font-medium">
            Row filter
          </h4>
          <div className="rounded-md border p-3">
            {v.row_filter_targeted ? (
              <Suspense fallback={<Skeleton className="h-40 w-full" />}>
                <RowFilterFlow principal={principal} table={table} />
              </Suspense>
            ) : (
              <p className="text-sm text-muted-foreground">
                No row filters apply to this table.
              </p>
            )}
          </div>
        </div>
        <div className="min-w-0 flex-1 basis-0 space-y-2">
          <h4 className="text-sm font-medium">
            Masked columns ({maskedColumns.length})
          </h4>
          <div className="divide-y rounded-md border">
            {maskedColumns.length > 0 ? (
              maskedColumns.map((column) => columnLink(column.column))
            ) : (
              <p className="px-3 py-2 text-sm text-muted-foreground">
                No columns are masked for this principal.
              </p>
            )}
          </div>
        </div>
      </div>
      <Separator />
      {v.can_read && (
        <div className="space-y-1">
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-sm font-medium">Chain graph</h4>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Switch
                checked={showUpstreamCascade}
                onCheckedChange={onShowUpstreamCascadeChange}
                aria-label="Show upstream cascade"
              />
              Upstream cascade
            </label>
          </div>
          <Suspense fallback={<Skeleton className="h-48 w-full" />}>
            <ChainGraph
              principal={principal}
              table={table}
              hideColumnMasks
              hideRowFilters
              hideUpstreamCascade={!showUpstreamCascade}
            />
          </Suspense>
        </div>
      )}
      {grantGroups.length > 0 && <GroupedChainDetail groups={grantGroups} />}
    </div>
  );
}

export function WhyPanel({
  principal,
  table,
  onClose,
  onColumnWhy,
}: {
  principal: string;
  table: string | null;
  onClose: () => void;
  onColumnWhy: (column: string) => void;
}) {
  const { search, update } = useViewerUrlState();
  const showUpstreamCascade = search.cascade === true;

  return (
    <Sheet open={table !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-full h-full overflow-hidden flex flex-col">
        <SheetHeader>
          <div className="flex items-start gap-3">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              aria-label="Back"
              onClick={onClose}
            >
              <ArrowLeft />
            </Button>
            <div>
              <SheetTitle className="font-mono text-base">Why?</SheetTitle>
              <SheetDescription className="font-mono text-xs">
                {principal} × {table}
              </SheetDescription>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <ModeToggle />
            </div>
          </div>
        </SheetHeader>
        <ScrollArea className="flex-1 pr-4">
          {table && (
            <Suspense fallback={<Skeleton className="h-64 w-full" />}>
              <WhyContent
                principal={principal}
                table={table}
                onColumnWhy={onColumnWhy}
                showUpstreamCascade={showUpstreamCascade}
                onShowUpstreamCascadeChange={(show) =>
                  void update({ cascade: show ? true : undefined })
                }
              />
            </Suspense>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
