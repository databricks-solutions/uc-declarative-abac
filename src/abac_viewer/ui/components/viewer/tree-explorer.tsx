import { Suspense, useMemo, useState, type ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
  ChevronsDown,
  ChevronsUp,
  CircleHelp,
  Columns3,
  Database,
  Folder,
  Table2,
} from "lucide-react";
import {
  useColumnsForPrincipalSuspense,
  useListColumnPoliciesSuspense,
  useListColumnsSuspense,
  useSecurableTreeSuspense,
  type TreeNodeOut,
} from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { FilterBadge, MaskBadge, StatusBadge } from "./status-badge";
import { PrincipalSelect, usePrincipal } from "./principal-context";
import { ColumnWhyPanel } from "./column-why-panel";
import { WhyPanel } from "./why-panel";
import { useViewerPrefetch } from "./use-viewer-prefetch";
import { useViewerUrlState } from "./viewer-url-state";

/** Unity Catalog-style tree explorer: pick a principal, browse
 * catalog → schema → table, select a table to see its columns' mask state.
 * A scalable alternative to the flat "columns" question. */

const ICON: Record<string, typeof Database> = {
  catalog: Database,
  schema: Folder,
  table: Table2,
};

export type CatalogEffect = "filter" | "mask";

function FastTooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full right-0 z-50 mb-1 whitespace-nowrap rounded border bg-popover px-1.5 py-0.5 text-[10px] text-popover-foreground opacity-0 shadow-sm group-hover:opacity-100 group-focus-within:opacity-100"
      >
        {label}
      </span>
    </span>
  );
}

function TreeEffectColumns({
  principal,
  table,
  effect,
  selectedColumn,
  depth,
  onSelect,
}: {
  principal: string;
  table: string;
  effect: CatalogEffect;
  selectedColumn?: string;
  depth: number;
  onSelect: (column: string) => void;
}) {
  const { data } = useColumnsForPrincipalSuspense({
    params: { principal, filter: "all", table },
  });
  const { prefetchColumnWhy } = useViewerPrefetch();
  const columns = data.data.filter((column) =>
    effect === "filter"
      ? column.row_filter_targeted
      : column.mask_targeted,
  );
  const label = effect === "filter" ? "Filtered columns" : "Masked columns";

  return (
    <div
      role="group"
      aria-label={`${label} for ${table}`}
      className="border-l border-border/70 py-1"
      style={{ marginLeft: depth * 16 + 38 }}
    >
      <div className="px-2 pb-1 text-[9px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      {columns.length > 0 ? (
        columns.map((column) => (
          <button
            type="button"
            key={column.column_full_name}
            data-tree-effect-column
            aria-current={selectedColumn === column.column_full_name}
            className={`flex w-full items-center gap-1.5 rounded-r px-2 py-1 text-left font-mono text-[11px] hover:bg-muted ${
              selectedColumn === column.column_full_name ? "bg-muted font-medium" : ""
            }`}
            onPointerEnter={() =>
              prefetchColumnWhy(principal, column.column_full_name)
            }
            onFocus={() => prefetchColumnWhy(principal, column.column_full_name)}
            onClick={() => onSelect(column.column_full_name)}
          >
            <span className="min-w-0 flex-1 truncate" title={column.column}>
              {column.column}
            </span>
            {effect === "filter" ? (
              <FilterBadge
                filtered={column.row_filtered}
                targeted={column.row_filter_targeted}
                compact
              />
            ) : (
              <MaskBadge
                masked={column.masked}
                targeted={column.mask_targeted}
                compact
              />
            )}
          </button>
        ))
      ) : (
        <p className="px-2 py-1 text-[11px] text-muted-foreground">None</p>
      )}
    </div>
  );
}

function PrincipalTreeColumns({
  principal,
  table,
  selectedColumn,
  depth,
  onSelect,
}: {
  principal: string;
  table: string;
  selectedColumn?: string;
  depth: number;
  onSelect?: (column: string, effect?: CatalogEffect) => void;
}) {
  const { data } = useColumnsForPrincipalSuspense({
    params: { principal, filter: "all", table },
  });
  return (
    <TreeColumnRows
      columns={data.data.map((column) => ({
        fullName: column.column_full_name,
        name: column.column,
        maskTargeted: column.mask_targeted,
        masked: column.masked,
      }))}
      table={table}
      selectedColumn={selectedColumn}
      depth={depth}
      onSelect={onSelect}
    />
  );
}

function InventoryTreeColumns({
  table,
  selectedColumn,
  depth,
  onSelect,
}: {
  table: string;
  selectedColumn?: string;
  depth: number;
  onSelect?: (column: string, effect?: CatalogEffect) => void;
}) {
  const { data } = useListColumnsSuspense({});
  const { data: policyData } = useListColumnPoliciesSuspense({});
  const prefix = `${table}.`;
  const policyByColumn = new Map(
    policyData.data.map((column) => [column.column_full_name, column]),
  );
  return (
    <TreeColumnRows
      columns={data.data
        .filter((column) => column.startsWith(prefix))
        .map((column) => ({
          fullName: column,
          name: column.slice(prefix.length),
          maskTargeted:
            (policyByColumn.get(column)?.mask_policy_count ?? 0) > 0,
        }))}
      table={table}
      selectedColumn={selectedColumn}
      depth={depth}
      onSelect={onSelect}
    />
  );
}

function TreeColumnRows({
  columns,
  table,
  selectedColumn,
  depth,
  onSelect,
}: {
  columns: Array<{
    fullName: string;
    name: string;
    maskTargeted?: boolean;
    masked?: boolean;
  }>;
  table: string;
  selectedColumn?: string;
  depth: number;
  onSelect?: (column: string, effect?: CatalogEffect) => void;
}) {
  return (
    <div
      role="group"
      aria-label={`Columns for ${table}`}
      className="border-l border-border/70 py-1"
      style={{ marginLeft: depth * 16 + 38 }}
    >
      <div className="px-2 pb-1 text-[9px] font-medium uppercase tracking-wide text-muted-foreground">
        Columns
      </div>
      {columns.map((column) => {
        const className = `flex w-full items-center gap-1.5 rounded-r px-2 py-1 text-left font-mono text-[11px] ${
          onSelect ? "hover:bg-muted" : ""
        } ${selectedColumn === column.fullName ? "bg-muted font-medium" : ""}`;
        const content = (
          <>
            <span className="min-w-0 flex-1 truncate" title={column.name}>
              {column.name}
            </span>
            {column.maskTargeted && (
              <MaskBadge
                masked={column.masked ?? true}
                targeted={column.masked === false}
                compact
              />
            )}
          </>
        );
        return onSelect ? (
          <button
            type="button"
            key={column.fullName}
            data-tree-column
            aria-current={selectedColumn === column.fullName}
            className={className}
            onClick={() =>
              onSelect(
                column.fullName,
                column.maskTargeted ? "mask" : undefined,
              )
            }
          >
            {content}
          </button>
        ) : (
          <div key={column.fullName} data-tree-column className={className}>
            {content}
          </div>
        );
      })}
    </div>
  );
}

function TreeColumns({
  principal,
  table,
  selectedColumn,
  depth,
  onSelect,
}: {
  principal?: string;
  table: string;
  selectedColumn?: string;
  depth: number;
  onSelect?: (column: string, effect?: CatalogEffect) => void;
}) {
  return principal ? (
    <PrincipalTreeColumns
      principal={principal}
      table={table}
      selectedColumn={selectedColumn}
      depth={depth}
      onSelect={onSelect}
    />
  ) : (
    <InventoryTreeColumns
      table={table}
      selectedColumn={selectedColumn}
      depth={depth}
      onSelect={onSelect}
    />
  );
}

function TreeRow({
  node,
  principal,
  depth,
  selected,
  expanded,
  onToggle,
  onSelect,
  onWhy,
  compact,
  columnsOpen,
  expandedColumns,
  selectedColumn,
  onColumnsToggle,
  onColumnSelect,
  activeEffect,
  effectTable,
  effectColumn,
  onEffect,
  onEffectColumn,
}: {
  node: TreeNodeOut;
  principal?: string;
  depth: number;
  selected: string | null;
  expanded: ReadonlySet<string>;
  onToggle: (fullName: string) => void;
  onSelect: (n: TreeNodeOut) => void;
  onWhy?: (table: string) => void;
  compact: boolean;
  columnsOpen: boolean;
  expandedColumns: ReadonlySet<string>;
  selectedColumn?: string;
  onColumnsToggle: (table: string) => void;
  onColumnSelect?: (column: string, effect?: CatalogEffect) => void;
  activeEffect?: CatalogEffect;
  effectTable?: string;
  effectColumn?: string;
  onEffect?: (table: string, effect: CatalogEffect) => void;
  onEffectColumn?: (column: string) => void;
}) {
  const { prefetchColumns, prefetchTableWhy } = useViewerPrefetch();
  const open = expanded.has(node.full_name);
  const hasChildren = (node.children?.length ?? 0) > 0;
  const isTable = node.securable_type === "table";
  const Icon = ICON[node.securable_type] ?? Table2;
  return (
    <div role="none">
      <div
        role="treeitem"
        aria-expanded={!isTable ? open : undefined}
        aria-selected={isTable ? selected === node.full_name : undefined}
        className={`flex w-full items-center rounded text-sm hover:bg-muted/60 ${
          selected === node.full_name ? "bg-muted" : ""
        }`}
        style={{ paddingLeft: depth * 16 + 8 }}
        onPointerEnter={() =>
          isTable && principal && prefetchColumns(principal, node.full_name)
        }
        onPointerDown={() =>
          isTable && principal && prefetchColumns(principal, node.full_name)
        }
        onFocus={() =>
          isTable && principal && prefetchColumns(principal, node.full_name)
        }
      >
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left"
          onClick={() => (isTable ? onSelect(node) : onToggle(node.full_name))}
        >
          {hasChildren || !isTable ? (
            open ? (
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            )
          ) : (
            <span className="w-3.5 shrink-0" />
          )}
          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span
            data-tree-label
            className="min-w-0 truncate font-mono text-xs"
            title={node.name}
          >
            {node.name}
          </span>
        </button>
        {isTable && node.readable === false && (
          <span data-tree-status className="shrink-0">
            <StatusBadge status="no_access" compact={compact} />
          </span>
        )}
        {isTable && node.readable !== false && (
          <span data-tree-status className="flex shrink-0 items-center gap-1">
            {node.row_filter_targeted &&
              (onEffect ? (
                <FastTooltip label="Row filter Why">
                  <button
                    type="button"
                    aria-label={`${
                      activeEffect === "filter" && effectTable === node.full_name
                        ? "Hide"
                        : "Show"
                    } row filter Why for ${node.full_name}`}
                    aria-pressed={
                      activeEffect === "filter" && effectTable === node.full_name
                    }
                    onClick={() => onEffect(node.full_name, "filter")}
                  >
                    <FilterBadge
                      filtered={node.row_filtered ?? false}
                      targeted
                      compact={compact}
                    />
                  </button>
                </FastTooltip>
              ) : (
                <FilterBadge
                  filtered={node.row_filtered ?? false}
                  targeted
                  compact={compact}
                />
              ))}
            {(node.mask_policy_column_count ?? 0) > 0 &&
              (onEffect ? (
                <FastTooltip label="Masked columns">
                  <button
                    type="button"
                    aria-label={`${
                      activeEffect === "mask" && effectTable === node.full_name
                        ? "Hide"
                        : "Show"
                    } masked columns for ${node.full_name}`}
                    aria-pressed={
                      activeEffect === "mask" && effectTable === node.full_name
                    }
                    onClick={() => onEffect(node.full_name, "mask")}
                  >
                    <MaskBadge
                      masked={(node.masked_column_count ?? 0) > 0}
                      targeted
                      compact={compact}
                    />
                  </button>
                </FastTooltip>
              ) : (
                <span title={`${node.masked_column_count}/${node.column_count} columns masked`}>
                  <MaskBadge
                    masked={(node.masked_column_count ?? 0) > 0}
                    targeted
                    compact={compact}
                  />
                </span>
              ))}
          </span>
        )}
        {isTable && (
          <FastTooltip label={columnsOpen ? "Hide columns" : "Show columns"}>
            <button
              type="button"
              className="inline-flex h-7 w-7 items-center justify-center rounded border border-border text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label={`${columnsOpen ? "Hide" : "Show"} all columns for ${node.full_name}`}
              aria-pressed={columnsOpen}
              onClick={() => onColumnsToggle(node.full_name)}
            >
              <Columns3 className="size-3.5" aria-hidden="true" />
            </button>
          </FastTooltip>
        )}
        {isTable && principal && onWhy && (compact ? (
          <FastTooltip label="Why?">
            <button
              type="button"
              data-tree-why
              className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-primary hover:bg-muted"
              aria-label={`Explain access to ${node.full_name}`}
              onPointerEnter={() => prefetchTableWhy(principal, node.full_name)}
              onPointerDown={() => prefetchTableWhy(principal, node.full_name)}
              onFocus={() => prefetchTableWhy(principal, node.full_name)}
              onClick={() => onWhy(node.full_name)}
            >
              <CircleHelp className="size-3.5" aria-hidden="true" />
              <span className="sr-only">Why?</span>
            </button>
          </FastTooltip>
        ) : (
          <button
            type="button"
            data-tree-why
            className="shrink-0 px-2 py-1 text-xs text-primary hover:underline"
            aria-label={`Explain access to ${node.full_name}`}
            onPointerEnter={() => prefetchTableWhy(principal, node.full_name)}
            onPointerDown={() => prefetchTableWhy(principal, node.full_name)}
            onFocus={() => prefetchTableWhy(principal, node.full_name)}
            onClick={() => onWhy(node.full_name)}
          >
            Why?
          </button>
        ))}
      </div>
      {isTable && columnsOpen && (
        <Suspense
          fallback={<Skeleton className="ml-10 h-16 w-[calc(100%-2.5rem)]" />}
        >
          <TreeColumns
            principal={principal}
            table={node.full_name}
            selectedColumn={selectedColumn}
            depth={depth}
            onSelect={onColumnSelect}
          />
        </Suspense>
      )}
      {isTable &&
        principal &&
        !columnsOpen &&
        activeEffect === "mask" &&
        effectTable === node.full_name &&
        onEffectColumn && (
          <Suspense fallback={<Skeleton className="ml-10 h-16 w-[calc(100%-2.5rem)]" />}>
            <TreeEffectColumns
              principal={principal}
              table={node.full_name}
              effect={activeEffect}
              selectedColumn={effectColumn}
              depth={depth}
              onSelect={onEffectColumn}
            />
          </Suspense>
        )}
      {open && hasChildren && (
        <div role="group">
          {node.children!.map((c) => (
            <TreeRow
              key={c.full_name}
              node={c}
              principal={principal}
              depth={depth + 1}
              selected={selected}
              expanded={expanded}
              onToggle={onToggle}
              onSelect={onSelect}
              onWhy={onWhy}
              compact={compact}
              columnsOpen={expandedColumns.has(c.full_name)}
              expandedColumns={expandedColumns}
              selectedColumn={selectedColumn}
              onColumnsToggle={onColumnsToggle}
              onColumnSelect={onColumnSelect}
              activeEffect={activeEffect}
              effectTable={effectTable}
              effectColumn={effectColumn}
              onEffect={onEffect}
              onEffectColumn={onEffectColumn}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function readableBranches(nodes: TreeNodeOut[]): TreeNodeOut[] {
  return nodes.flatMap((node) => {
    if (node.securable_type === "table") {
      return node.readable ? [node] : [];
    }
    const children = readableBranches(node.children ?? []);
    return children.length > 0 ? [{ ...node, children }] : [];
  });
}

function branchNames(nodes: TreeNodeOut[]): string[] {
  return nodes.flatMap((node) =>
    node.securable_type === "table"
      ? []
      : [node.full_name, ...branchNames(node.children ?? [])],
  );
}

export function CatalogTree({
  principal,
  selected,
  hideInaccessible,
  onHideInaccessibleChange,
  onSelect,
  onWhy,
  compact = false,
  activeEffect,
  effectTable,
  effectColumn,
  onEffect,
  onEffectColumn,
  selectedColumn,
  onColumnSelect,
}: {
  principal?: string;
  selected: string | null;
  hideInaccessible: boolean;
  onHideInaccessibleChange: (checked: boolean) => void;
  onSelect: (n: TreeNodeOut) => void;
  onWhy?: (table: string) => void;
  compact?: boolean;
  activeEffect?: CatalogEffect;
  effectTable?: string;
  effectColumn?: string;
  onEffect?: (table: string, effect: CatalogEffect) => void;
  onEffectColumn?: (column: string) => void;
  selectedColumn?: string;
  onColumnSelect?: (column: string, effect?: CatalogEffect) => void;
}) {
  const { data } = useSecurableTreeSuspense({ params: { principal } });
  const [expanded, setExpanded] = useState<Set<string>>(
    () =>
      new Set(
        branchNames(principal ? readableBranches(data.data) : data.data),
      ),
  );
  const [expandedColumns, setExpandedColumns] = useState<Set<string>>(
    () => new Set(),
  );
  const nodes = useMemo(
    () =>
      principal && hideInaccessible ? readableBranches(data.data) : data.data,
    [data.data, hideInaccessible, principal],
  );
  const toggle = (fullName: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(fullName)) next.delete(fullName);
      else next.add(fullName);
      return next;
    });
  };
  const toggleColumns = (table: string) => {
    const openingColumns = !expandedColumns.has(table);
    if (
      openingColumns &&
      activeEffect &&
      effectTable === table &&
      onEffect
    ) {
      onEffect(table, activeEffect);
    }
    setExpandedColumns((current) => {
      const next = new Set(current);
      if (next.has(table)) next.delete(table);
      else next.add(table);
      return next;
    });
  };
  const selectEffect = (table: string, effect: CatalogEffect) => {
    setExpandedColumns((current) => {
      if (!current.has(table)) return current;
      const next = new Set(current);
      next.delete(table);
      return next;
    });
    onEffect?.(table, effect);
  };

  return (
    <div className="rounded-md border overflow-hidden">
      <div className="flex items-center gap-2 border-b px-2 py-1.5">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="Expand all"
            aria-label="Expand all catalog branches"
            onClick={() => setExpanded(new Set(branchNames(nodes)))}
          >
            <ChevronsDown />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="Collapse all"
            aria-label="Collapse all catalog branches"
            onClick={() => setExpanded(new Set())}
          >
            <ChevronsUp />
          </Button>
        </div>
        {principal && (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Switch
              checked={hideInaccessible}
              onCheckedChange={onHideInaccessibleChange}
              aria-label="Hide inaccessible catalog branches"
            />
            Hide inaccessible
          </label>
        )}
      </div>
      <div
        role="tree"
        aria-label={`Catalog access for ${principal ?? "all principals"}`}
        className="p-2 overflow-auto max-h-[70vh]"
      >
        {nodes.length > 0 ? (
          nodes.map((node) => (
            <TreeRow
              key={node.full_name}
              node={node}
              principal={principal}
              depth={0}
              selected={selected}
              expanded={expanded}
              onToggle={toggle}
              onSelect={onSelect}
              onWhy={onWhy}
              compact={compact}
              columnsOpen={expandedColumns.has(node.full_name)}
              expandedColumns={expandedColumns}
              selectedColumn={selectedColumn}
              onColumnsToggle={toggleColumns}
              onColumnSelect={onColumnSelect}
              activeEffect={activeEffect}
              effectTable={effectTable}
              effectColumn={effectColumn}
              onEffect={onEffect ? selectEffect : undefined}
              onEffectColumn={onEffectColumn}
            />
          ))
        ) : (
          <p className="p-2 text-xs text-muted-foreground">
            No readable tables for {principal ?? "all principals"}.
          </p>
        )}
      </div>
    </div>
  );
}

function ColumnPanel({
  principal,
  table,
  onWhy,
}: {
  principal: string;
  table: string;
  onWhy: (columnFullName: string) => void;
}) {
  const { data } = useColumnsForPrincipalSuspense({
    params: { principal, filter: "all", table },
  });
  const { prefetchColumnWhy } = useViewerPrefetch();
  const cols = data.data;
  if (cols.length === 0) {
    return (
      <p className="text-sm text-muted-foreground p-4">
        No readable columns for {principal} in {table} (they may lack table
        access).
      </p>
    );
  }
  return (
    <div className="divide-y overflow-x-auto">
      {cols.map((c) => (
        <div
          key={c.column_full_name}
          className="grid min-w-[28rem] cursor-pointer grid-cols-[minmax(7rem,1fr)_6rem_6.5rem_3rem] items-center gap-3 px-3 py-2 text-sm hover:bg-muted/60 focus-visible:bg-muted"
          role="button"
          tabIndex={0}
          aria-label={`Explain ${c.column_full_name}`}
          onPointerEnter={() => prefetchColumnWhy(principal, c.column_full_name)}
          onPointerDown={() => prefetchColumnWhy(principal, c.column_full_name)}
          onFocus={() => prefetchColumnWhy(principal, c.column_full_name)}
          onClick={() => onWhy(c.column_full_name)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onWhy(c.column_full_name);
            }
          }}
        >
          <span
            className="min-w-0 truncate font-mono text-xs font-medium"
            title={c.column}
          >
            {c.column}
          </span>
          <span className="font-mono text-[11px] text-muted-foreground">
            {c.data_type ?? ""}
          </span>
          <span>
            <MaskBadge masked={c.masked} targeted={c.mask_targeted} />
          </span>
          <span className="justify-self-end text-xs text-primary">
            Why?
          </span>
        </div>
      ))}
    </div>
  );
}

export function TreeExplorer() {
  const { principal } = usePrincipal();
  const { search, update, openWhy, closeWhy } = useViewerUrlState();
  const selectedTable = search.table ?? null;
  const hideInaccessible = search.hide !== false;
  const tableWhy = search.why === "table" ? search.target ?? null : null;
  const colWhy = search.why === "column" ? search.target ?? null : null;
  const whyPrincipal = search.wp ?? principal;

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Principal</label>
        <Suspense fallback={<Skeleton className="h-9 w-72" />}>
          <PrincipalSelect />
        </Suspense>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Suspense fallback={<Skeleton className="h-64 w-full" />}>
          <CatalogTree
            key={principal}
            principal={principal}
            selected={selectedTable}
            hideInaccessible={hideInaccessible}
            onHideInaccessibleChange={(checked) =>
              void update({ hide: checked })
            }
            onSelect={(node) => {
              const whyTable =
                tableWhy ?? colWhy?.split(".").slice(0, 3).join(".");
              const closeDifferentWhy =
                Boolean(whyTable) && whyTable !== node.full_name;
              void update({
                table: node.full_name,
                why: closeDifferentWhy ? undefined : search.why,
                target: closeDifferentWhy ? undefined : search.target,
                wp: closeDifferentWhy ? undefined : search.wp,
                maskFlow: closeDifferentWhy ? undefined : search.maskFlow,
                filterFlow: closeDifferentWhy ? undefined : search.filterFlow,
                tableAccess: closeDifferentWhy ? undefined : search.tableAccess,
                cascade: closeDifferentWhy ? undefined : search.cascade,
              });
            }}
            onWhy={(table) => void openWhy("table", table)}
          />
        </Suspense>
        <div className="rounded-md border">
          <div className="border-b px-3 py-2 text-xs text-muted-foreground font-mono">
            {selectedTable ?? "Select a table to see its columns"}
          </div>
          {selectedTable && (
            <Suspense fallback={<Skeleton className="h-40 w-full" />}>
              <ColumnPanel
                principal={principal}
                table={selectedTable}
                onWhy={(column) => void openWhy("column", column, principal)}
              />
            </Suspense>
          )}
        </div>
      </div>
      <ColumnWhyPanel
        principal={whyPrincipal}
        column={colWhy}
        onClose={closeWhy}
      />
      <WhyPanel
        principal={principal}
        table={tableWhy}
        onClose={closeWhy}
        onColumnWhy={(column) => {
          void openWhy("column", column, principal, { replace: true });
        }}
      />
    </div>
  );
}
