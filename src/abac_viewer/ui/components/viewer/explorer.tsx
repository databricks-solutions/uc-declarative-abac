import { Suspense, type KeyboardEvent } from "react";
import {
  useAccessForPrincipalSuspense,
  useColumnsForPrincipalSuspense,
  useListColumnsSuspense,
  useWhoCanSeeSuspense,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AccessBadge,
  FilterBadge,
  MaskBadge,
  StatusBadge,
} from "./status-badge";
import { PrincipalSelect, usePrincipal } from "./principal-context";
import { WhyPanel } from "./why-panel";
import { ColumnWhyPanel } from "./column-why-panel";
import { useViewerPrefetch } from "./use-viewer-prefetch";
import {
  useViewerUrlState,
  type ExplorerQuestion,
} from "./viewer-url-state";

/** Explorer (Q&A) view — question dropdown + context-dependent parameter
 * dropdown, per the deck mockups. Every result row carries a "Why?" link. */

const QUESTIONS = [
  { id: "tables", label: "Which tables can a principal read?" },
  { id: "columns", label: "Which columns can a principal read" },
  { id: "who", label: "Who can see a column?" },
] as const;

function activateRow(event: KeyboardEvent, action: () => void) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    action();
  }
}

function ColumnSelect({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (v: string) => void;
}) {
  const { data } = useListColumnsSuspense({});
  return (
    <Select value={value ?? undefined} onValueChange={onChange}>
      <SelectTrigger className="w-full font-mono text-xs sm:w-96">
        <SelectValue placeholder="column…" />
      </SelectTrigger>
      <SelectContent>
        {data.data.map((c) => (
          <SelectItem key={c} value={c} className="font-mono text-xs">
            {c}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function TablesResult({
  principal,
  hideInaccessible,
  onWhy,
}: {
  principal: string;
  hideInaccessible: boolean;
  onWhy: (table: string) => void;
}) {
  const { data } = useAccessForPrincipalSuspense({ params: { principal } });
  const { prefetchTableWhy } = useViewerPrefetch();
  const rows = hideInaccessible
    ? data.data.filter((row) => row.status !== "no_access")
    : data.data;
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No readable tables for this principal.
      </p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Table</TableHead>
          <TableHead>Access</TableHead>
          <TableHead>Masked columns</TableHead>
          <TableHead>Tags</TableHead>
          <TableHead className="text-right">Explain</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow
            key={row.securable}
            className="cursor-pointer focus-visible:bg-muted"
            tabIndex={0}
            aria-label={`Explain access to ${row.securable}`}
            onPointerEnter={() => prefetchTableWhy(principal, row.securable)}
            onPointerDown={() => prefetchTableWhy(principal, row.securable)}
            onFocus={() => prefetchTableWhy(principal, row.securable)}
            onClick={() => onWhy(row.securable)}
            onKeyDown={(event) =>
              activateRow(event, () => onWhy(row.securable))
            }
          >
            <TableCell className="font-mono text-xs">{row.securable}</TableCell>
            <TableCell>
              <div className="flex gap-1 flex-wrap">
                <StatusBadge status={row.status} />
                {row.row_filtered && row.status !== "no_access" && (
                  <FilterBadge filtered />
                )}
              </div>
            </TableCell>
            <TableCell className="font-mono text-xs">
              {row.status !== "no_access" && row.masked_columns.length > 0 ? (
                <div className="flex items-center gap-2">
                  <MaskBadge masked />
                  <span>{row.masked_columns.join(", ")}</span>
                </div>
              ) : (
                "—"
              )}
            </TableCell>
            <TableCell>
              <div className="flex gap-1 flex-wrap">
                {Object.entries(row.tags ?? {}).length > 0 ? (
                  Object.entries(row.tags ?? {}).map(([k, v]) => (
                    <Badge key={k} variant="secondary" className="font-mono text-[10px]">
                      {k}={v}
                    </Badge>
                  ))
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </div>
            </TableCell>
            <TableCell className="text-right">
              <Button
                variant="link"
                size="sm"
                className="text-xs"
                onClick={(event) => {
                  event.stopPropagation();
                  onWhy(row.securable);
                }}
              >
                Why?
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function ColumnsResult({
  principal,
  hideInaccessible,
  onWhy,
}: {
  principal: string;
  hideInaccessible: boolean;
  onWhy: (columnFullName: string) => void;
}) {
  const { data } = useColumnsForPrincipalSuspense({
    params: {
      principal,
      filter: "all",
      include_inaccessible: !hideInaccessible,
    },
  });
  const { prefetchColumnWhy } = useViewerPrefetch();
  if (data.data.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No readable columns for this principal.
      </p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Column</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Access</TableHead>
          <TableHead>Mask</TableHead>
          <TableHead>Row filter</TableHead>
          <TableHead>Via policy</TableHead>
          <TableHead>Tags</TableHead>
          <TableHead className="text-right">Explain</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.data.map((row) => (
          <TableRow
            key={row.column_full_name}
            className="cursor-pointer focus-visible:bg-muted"
            tabIndex={0}
            aria-label={`Explain ${row.column_full_name}`}
            onPointerEnter={() =>
              prefetchColumnWhy(principal, row.column_full_name)
            }
            onPointerDown={() =>
              prefetchColumnWhy(principal, row.column_full_name)
            }
            onFocus={() => prefetchColumnWhy(principal, row.column_full_name)}
            onClick={() => onWhy(row.column_full_name)}
            onKeyDown={(event) =>
              activateRow(event, () => onWhy(row.column_full_name))
            }
          >
            <TableCell className="font-mono text-xs font-medium">
              {row.column_full_name}
            </TableCell>
            <TableCell className="font-mono text-[11px] text-muted-foreground">
              {row.data_type ?? ""}
            </TableCell>
            <TableCell>
              <AccessBadge canRead={row.can_read_table} />
            </TableCell>
            <TableCell>
              {row.can_read_table ? (
                <MaskBadge masked={row.masked} targeted={row.mask_targeted} />
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell>
              {row.can_read_table && row.row_filter_targeted ? (
                <FilterBadge filtered={row.row_filtered} targeted />
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell className="font-mono text-[11px] text-muted-foreground">
              {row.can_read_table ? row.policy_name ?? "—" : "—"}
            </TableCell>
            <TableCell>
              <div className="flex gap-1 flex-wrap">
                {Object.entries(row.tags ?? {}).length > 0 ? (
                  Object.entries(row.tags ?? {}).map(([k, v]) => (
                    <Badge key={k} variant="secondary" className="font-mono text-[10px]">
                      {k}={v}
                    </Badge>
                  ))
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </div>
            </TableCell>
            <TableCell className="text-right">
              <Button
                variant="link"
                size="sm"
                className="text-xs"
                onClick={(event) => {
                  event.stopPropagation();
                  onWhy(row.column_full_name);
                }}
              >
                Why?
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function WhoResult({
  column,
  onWhy,
}: {
  column: string;
  onWhy: (principal: string) => void;
}) {
  const { data } = useWhoCanSeeSuspense({ params: { column } });
  const { prefetchColumnWhy } = useViewerPrefetch();
  if (data.data.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No principals can read this column.
      </p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Principal</TableHead>
          <TableHead>Mask</TableHead>
          <TableHead>Row filter</TableHead>
          <TableHead className="text-right">Explain</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.data.map((row) => (
          <TableRow
            key={row.principal}
            className="cursor-pointer focus-visible:bg-muted"
            tabIndex={0}
            aria-label={`Explain visibility for ${row.principal}`}
            onPointerEnter={() => prefetchColumnWhy(row.principal, column)}
            onPointerDown={() => prefetchColumnWhy(row.principal, column)}
            onFocus={() => prefetchColumnWhy(row.principal, column)}
            onClick={() => onWhy(row.principal)}
            onKeyDown={(event) =>
              activateRow(event, () => onWhy(row.principal))
            }
          >
            <TableCell className="font-mono text-xs">{row.principal}</TableCell>
            <TableCell>
              <MaskBadge masked={row.masked} targeted={row.mask_targeted} />
            </TableCell>
            <TableCell>
              {row.row_filter_targeted ? (
                <FilterBadge filtered={row.row_filtered} targeted />
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell className="text-right">
              <Button
                variant="link"
                size="sm"
                className="text-xs"
                onClick={(event) => {
                  event.stopPropagation();
                  onWhy(row.principal);
                }}
              >
                Why?
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function Explorer() {
  const { principal } = usePrincipal();
  const { search, update, openWhy, closeWhy } = useViewerUrlState();
  const question = search.q ?? "tables";
  const column = search.column ?? null;
  const hideInaccessible = search.hide !== false;
  const tableWhy = search.why === "table" ? search.target ?? null : null;
  const colWhy = search.why === "column" ? search.target ?? null : null;
  const colWhyPrincipal = search.wp ?? principal;

  return (
    <div className="space-y-4">
      <div className="flex items-end gap-3 flex-wrap">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Question</label>
          <Select
            value={question}
            onValueChange={(value) =>
              void update({
                q: value as ExplorerQuestion,
                column: value === "who" ? search.column : undefined,
              })
            }
          >
            <SelectTrigger className="w-full text-sm sm:w-96">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {QUESTIONS.map((q) => (
                <SelectItem key={q.id} value={q.id}>
                  {q.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            {question === "who" ? "Column" : "Principal"}
          </label>
          <Suspense fallback={<Skeleton className="h-9 w-72" />}>
            {question === "who" ? (
              <ColumnSelect
                value={column}
                onChange={(value) => void update({ column: value })}
              />
            ) : (
              <PrincipalSelect />
            )}
          </Suspense>
        </div>
        {(question === "tables" || question === "columns") && (
          <label className="flex h-9 items-center gap-2 text-xs text-muted-foreground">
            <Switch
              checked={hideInaccessible}
              onCheckedChange={(checked) => void update({ hide: checked })}
              aria-label="Hide inaccessible results"
            />
            Hide inaccessible
          </label>
        )}
      </div>

      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        {question === "tables" && (
          <TablesResult
            principal={principal}
            hideInaccessible={hideInaccessible}
            onWhy={(table) => void openWhy("table", table)}
          />
        )}
        {question === "columns" && (
          <ColumnsResult
            principal={principal}
            hideInaccessible={hideInaccessible}
            onWhy={(col) => void openWhy("column", col, principal)}
          />
        )}
        {question === "who" &&
          (column ? (
            <WhoResult
              column={column}
              onWhy={(p) => void openWhy("column", column, p)}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              Pick a column to see who can read it.
            </p>
          ))}
      </Suspense>

      <WhyPanel
        principal={principal}
        table={tableWhy}
        onClose={closeWhy}
        onColumnWhy={(column) => {
          void openWhy("column", column, principal, { replace: true });
        }}
      />
      <ColumnWhyPanel
        principal={colWhyPrincipal}
        column={colWhy}
        onClose={closeWhy}
      />
    </div>
  );
}
