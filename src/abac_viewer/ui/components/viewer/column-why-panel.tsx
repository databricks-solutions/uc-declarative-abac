import { Suspense } from "react";
import {
  useExplainColumnSuspense,
  type ChainGraphNodeOut,
  type ChainGraphOut,
  type ColumnExplanationOut,
} from "@/lib/api";
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
import { ArrowLeft, CircleCheck, ExternalLink } from "lucide-react";
import { ChainGraph, ChainGraphSteps, ColumnChainGraph } from "./chain-graph";
import { useGithubLinker } from "./github-link";
import { FilterBadge, MaskBadge } from "./status-badge";
import { useViewerUrlState } from "./viewer-url-state";
import { RowFilterFlow } from "./row-filter-flow";

/** Column Why page. Three sections, each toggleable:
 *   (a) table read-access chain (why the principal can read the table at all)
 *   (b) simplified mask flow via policy → tag → column [default on]
 *   (c) policy attachment (temporarily feature-flagged off)
 * The goal: a beginner sees only (b); an admin can reveal (a).
 *
 * Section (b) is prototyped two ways — graph vs. numbered steps — with a
 * small toggle so we can compare them. */

type SectionToggle = { a: boolean; b: boolean; c: boolean; d: boolean };
type DisplayMode = "graph" | "steps";
const SHOW_POLICY_ATTACHMENT =
  import.meta.env.VITE_SHOW_POLICY_ATTACHMENT === "true";

/** (c) Where the deciding mask policy is *applied* — the securable whose
 * `policies:` list declares it (e.g. the demo catalog). This is distinct
 * from where the tag sits (the column); it answers "at what level is the mask
 * attached?". */
function PolicyAttachment({ exp }: { exp: ColumnExplanationOut }) {
  const linker = useGithubLinker();
  if (exp.policy_name == null) {
    return (
      <p className="text-sm text-muted-foreground">
        No mask policy targets {exp.column}, so there is no policy attachment to
        show.
      </p>
    );
  }
  if (exp.policy_attached_to == null) {
    return (
      <p className="text-sm text-muted-foreground">
        Attachment point unknown for policy '{exp.policy_name}'.
      </p>
    );
  }
  const href = linker(exp.policy_source);
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <PolicyAttachmentDiagram exp={exp} />
      <div className="rounded-md border p-3 space-y-1.5">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium">{exp.policy_name}</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground rounded bg-muted px-1.5 py-0.5">
            mask policy
          </span>
        </div>
        <div className="text-sm">
          applied at <span className="font-mono">{exp.policy_attached_to}</span>
          {exp.policy_attached_level && (
            <span className="ml-1.5 text-[10px] uppercase tracking-wider text-muted-foreground rounded bg-muted px-1.5 py-0.5">
              {exp.policy_attached_level} level
            </span>
          )}
        </div>
        {exp.policy_source && (
          <div className="text-[11px] font-mono text-muted-foreground/80">
            {href ? (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 hover:underline"
              >
                ↳ {exp.policy_source}
                <ExternalLink className="h-3 w-3" />
              </a>
            ) : (
              <>↳ {exp.policy_source}</>
            )}
          </div>
        )}
        <p className="text-[11px] text-muted-foreground pt-1">
          The policy cascades from here to every column beneath it whose tag
          matches — including {exp.column}.
        </p>
      </div>
    </div>
  );
}

/** Vertical containment ladder (catalog → schema → table → column) with the
 * mask policy pinned at its attachment level and a cascade arrow down to the
 * target column, which is highlighted. */
function PolicyAttachmentDiagram({ exp }: { exp: ColumnExplanationOut }) {
  const LEVELS = ["catalog", "schema", "table", "column"] as const;
  const parts = exp.column_full_name.split(".");
  // parts: [catalog, schema, table, column] (may have fewer for edge configs)
  const rows = LEVELS.map((level, i) => ({
    level,
    name: parts[i] ?? level,
    isAttach: exp.policy_attached_level === level,
    isTarget: level === "column",
  }));
  const attachIdx = rows.findIndex((r) => r.isAttach);
  return (
    <div className="rounded-md border p-3">
      <div className="space-y-0">
        {rows.map((r, i) => (
          <div key={r.level}>
            <div
              className="flex items-center gap-2 rounded-md px-2 py-1.5"
              style={{ marginLeft: i * 14 }}
            >
              <span
                className="inline-block size-2.5 rounded-sm"
                style={{
                  background: r.isTarget
                    ? "var(--graph-securable)"
                    : "var(--muted-foreground)",
                }}
              />
              <span
                className={`font-mono text-xs ${r.isTarget ? "font-semibold" : ""}`}
              >
                {r.name}
              </span>
              <span className="text-[9px] uppercase tracking-wider text-muted-foreground">
                {r.level}
              </span>
              {r.isAttach && (
                <span className="ml-auto inline-flex items-center gap-1 rounded bg-[#eb6834]/12 px-1.5 py-0.5 text-[10px] font-medium text-[#c2410c] dark:text-[#ff9b73]">
                  <span className="inline-block size-1.5 rounded-full bg-[var(--graph-policy)]" />
                  {exp.policy_name}
                </span>
              )}
            </div>
            {/* cascade connector between the attach level and the column */}
            {attachIdx >= 0 && i >= attachIdx && i < rows.length - 1 && (
              <div
                className="text-[#c2410c]/70 dark:text-[#ff9b73]/80 text-xs leading-none"
                style={{ marginLeft: i * 14 + 6 }}
              >
                ↓
              </div>
            )}
          </div>
        ))}
      </div>
      <p className="text-[10px] text-muted-foreground mt-2">
        Attached at{" "}
        <span className="font-mono">{exp.policy_attached_level}</span>; cascades
        down to the tagged column.
      </p>
    </div>
  );
}

function NumberedSteps({ exp }: { exp: ColumnExplanationOut }) {
  const steps: string[] = [];
  const p = exp.principal;
  if (exp.policy_name == null) {
    steps.push(`No mask policy targets ${exp.column} — ${p} sees it unmasked.`);
  } else {
    const tags =
      Object.entries(exp.tag_atoms)
        .map(([k, v]) => `${k}=${v}`)
        .join(", ") || "a tag";
    steps.push(`Column ${exp.column} is tagged ${tags}.`);
    steps.push(
      `Mask policy '${exp.policy_name}' targets that tag${exp.function ? ` (function ${exp.function})` : ""}.`,
    );
    if (exp.arguments.length > 1) {
      const argumentsText = exp.arguments
        .map((argument) => {
          if (argument.kind === "constant") {
            return `#${argument.position} ${argument.constant_type} constant ${JSON.stringify(argument.constant)}`;
          }
          const role = argument.target ? "mask target" : "using column";
          return `#${argument.position} ${role} ${argument.alias} → ${argument.matched_columns.join(", ")}`;
        })
        .join("; ");
      steps.push(`Function arguments: ${argumentsText}.`);
    }
    if (exp.masked) {
      steps.push(
        `${p} is covered by the policy's 'to' (${exp.covered_by}) and not exempt → the column is MASKED.`,
      );
    } else if (exp.excepted_by) {
      steps.push(
        `${p} is exempt via the policy's 'except' (${exp.excepted_by}) → the column is shown UNMASKED.`,
      );
    } else {
      steps.push(
        `${p} is not in the policy's 'to' list → the policy does not apply → shown UNMASKED.`,
      );
    }
  }
  return (
    <ol className="space-y-2">
      {steps.map((s, i) => (
        <li key={i} className="flex gap-3 text-sm">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
            {i + 1}
          </span>
          <span>{s}</span>
        </li>
      ))}
    </ol>
  );
}

export function ColumnWhyContent({
  principal,
  column,
  focus,
  inline = false,
  selectedNodeId,
  onNodeActivate,
  onGraphChange,
}: {
  principal: string;
  column: string;
  focus?: "filter" | "mask";
  inline?: boolean;
  selectedNodeId?: string;
  onNodeActivate?: (node: ChainGraphNodeOut) => void;
  onGraphChange?: (graph: ChainGraphOut) => void;
}) {
  const { data } = useExplainColumnSuspense({ params: { principal, column } });
  const exp = data.data;
  const { search, update } = useViewerUrlState();
  const show: SectionToggle = {
    a: inline ? false : search.tableAccess === true,
    b: inline ? focus === "mask" : search.maskFlow !== false,
    c: false,
    d: inline ? focus === "filter" : search.filterFlow !== false,
  };
  const displayMode: DisplayMode = search.mode ?? "graph";
  const showUpstreamCascade = search.cascade === true;

  const toggle = (key: keyof SectionToggle) => {
    if (key === "a") void update({ tableAccess: !show.a });
    if (key === "b") void update({ maskFlow: !show.b });
    if (key === "d") void update({ filterFlow: !show.d });
  };

  return (
    <div className={inline ? "space-y-2" : "space-y-4"}>
      {!inline && (
        <div className="flex items-center gap-2 flex-wrap">
          <MaskBadge masked={exp.masked} targeted={exp.policy_name !== null} />
          {exp.row_filter_targeted && (
            <FilterBadge filtered={exp.row_filtered} targeted />
          )}
          {!exp.can_read_table && (
            <span className="text-[11px] text-muted-foreground">
              (principal cannot read the table — mask is moot)
            </span>
          )}
        </div>
      )}
      {!inline && <p className="text-sm leading-relaxed">{exp.sentence}</p>}

      {show.b && exp.excepted_by && (
        <div
          data-mask-exemption
          className="flex items-start gap-2 rounded-md border border-emerald-300 bg-emerald-100 p-3 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
        >
          <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="space-y-0.5 text-xs">
            <p className="font-semibold">Exempt from masking</p>
            <p>
              <span className="font-mono">{exp.principal}</span> is exempt via{" "}
              <span className="font-mono">{exp.excepted_by}</span>. The mask
              policy does not apply, so{" "}
              <span className="font-mono">{exp.column}</span> remains unmasked.
            </p>
          </div>
        </div>
      )}

      {show.d && exp.row_filter_excepted_by && (
        <div
          data-filter-exemption
          className="flex items-start gap-2 rounded-md border border-emerald-300 bg-emerald-100 p-3 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
        >
          <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="space-y-0.5 text-xs">
            <p className="font-semibold">Exempt from row filtering</p>
            <p>
              <span className="font-mono">{exp.principal}</span> is exempt via{" "}
              <span className="font-mono">{exp.row_filter_excepted_by}</span>.
              The row-filter policy does not apply, so all rows remain visible.
            </p>
          </div>
        </div>
      )}

      {/* section toggles */}
      {!inline && (
        <div className="flex flex-wrap gap-x-6 gap-y-2 rounded-md border p-3">
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={show.b} onCheckedChange={() => toggle("b")} />
            Mask flow
          </label>
          {exp.row_filter_targeted && (
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={show.d} onCheckedChange={() => toggle("d")} />
              Row filter flow
            </label>
          )}
          {SHOW_POLICY_ATTACHMENT && (
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={show.c} onCheckedChange={() => toggle("c")} />
              Policy attachment
            </label>
          )}
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={show.a}
              onCheckedChange={() => toggle("a")}
              aria-label="Show table read access"
            />
            Table read access
          </label>
          <div className="ml-auto flex gap-1">
            <Button
              size="sm"
              variant={displayMode === "graph" ? "default" : "outline"}
              className="h-7 text-xs"
              onClick={() => void update({ mode: "graph" })}
            >
              Graph
            </Button>
            <Button
              size="sm"
              variant={displayMode === "steps" ? "default" : "outline"}
              className="h-7 text-xs"
              onClick={() => void update({ mode: "steps" })}
            >
              Steps
            </Button>
          </div>
        </div>
      )}

      {/* (b) simplified mask flow through the matched tag */}
      {show.b && (
        <div className="space-y-2">
          {!inline && <h4 className="text-sm font-medium">Mask flow</h4>}
          {displayMode === "graph" ? (
            <Suspense fallback={<Skeleton className="h-40 w-full" />}>
              <ColumnChainGraph
                principal={principal}
                column={column}
                hideDirectColumnEdges
                selectedNodeId={selectedNodeId}
                onNodeActivate={onNodeActivate}
                onGraphChange={onGraphChange}
              />
            </Suspense>
          ) : (
            <div className="rounded-md border p-3">
              <NumberedSteps exp={exp} />
            </div>
          )}
        </div>
      )}

      {exp.row_filter_targeted && show.d && (
        <>
          {!inline && <Separator />}
          <div className="space-y-2">
            {!inline && (
              <>
                <h4 className="text-sm font-medium">Row filter flow</h4>
                <p className="text-[11px] text-muted-foreground">
                  Row-filter policies affecting {exp.table_full_name}, separate
                  from the grants that make the table readable.
                </p>
              </>
            )}
            <Suspense fallback={<Skeleton className="h-40 w-full" />}>
              <RowFilterFlow
                principal={principal}
                table={exp.table_full_name}
                mode={displayMode}
                selectedNodeId={selectedNodeId}
                onNodeActivate={onNodeActivate}
                onGraphChange={onGraphChange}
                showExemption={false}
                focusColumn={exp.column}
              />
            </Suspense>
          </div>
        </>
      )}

      {/* (c) policy attachment — where the mask policy is applied (e.g. catalog) */}
      {SHOW_POLICY_ATTACHMENT && show.c && (
        <>
          <Separator />
          <div className="space-y-2">
            <h4 className="text-sm font-medium">Policy attachment</h4>
            <p className="text-[11px] text-muted-foreground">
              Where the deciding mask policy is applied in the config — the
              securable whose <code>policies:</code> list declares it.
            </p>
            <PolicyAttachment exp={exp} />
          </div>
        </>
      )}

      {/* (a) table read-access chain */}
      {show.a && (
        <>
          <Separator />
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <h4 className="text-sm font-medium">Table read access</h4>
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <Switch
                  checked={showUpstreamCascade}
                  onCheckedChange={(checked) =>
                    void update({ cascade: checked ? true : undefined })
                  }
                  aria-label="Show upstream cascade"
                />
                Upstream cascade
              </label>
            </div>
            <p className="text-[11px] text-muted-foreground">
              Why {principal} can read {exp.table_full_name} at all (a separate
              concern from masking).
            </p>
            {exp.can_read_table ? (
              <Suspense fallback={<Skeleton className="h-40 w-full" />}>
                {displayMode === "graph" ? (
                  <ChainGraph
                    principal={principal}
                    table={exp.table_full_name}
                    hideColumnMasks
                    hideRowFilters
                    hideUpstreamCascade={!showUpstreamCascade}
                  />
                ) : (
                  <ChainGraphSteps
                    principal={principal}
                    table={exp.table_full_name}
                    hideColumnMasks
                    hideRowFilters
                    hideUpstreamCascade={!showUpstreamCascade}
                  />
                )}
              </Suspense>
            ) : (
              <p className="text-sm text-muted-foreground">
                {principal} cannot read {exp.table_full_name}.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function ColumnWhyPanel({
  principal,
  column,
  onClose,
}: {
  principal: string;
  column: string | null;
  onClose: () => void;
}) {
  return (
    <Sheet open={column !== null} onOpenChange={(open) => !open && onClose()}>
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
              <SheetTitle className="font-mono text-base">
                Why? (column)
              </SheetTitle>
              <SheetDescription className="font-mono text-xs">
                {principal} × {column}
              </SheetDescription>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <ModeToggle />
            </div>
          </div>
        </SheetHeader>
        <ScrollArea className="flex-1 pr-4">
          {column && (
            <Suspense fallback={<Skeleton className="h-64 w-full" />}>
              <ColumnWhyContent principal={principal} column={column} />
            </Suspense>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
