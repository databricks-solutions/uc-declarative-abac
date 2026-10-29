import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Network, Search, Users, X } from "lucide-react";
import {
  useAccessGraphSuspense,
  useColumnsForPrincipalSuspense,
  useInverseAccessGraphSuspense,
  type ChainGraphEdgeOut,
  type ChainGraphNodeOut,
  type ChainGraphOut,
  type GraphEdgeOut,
  type PrincipalEffectOut,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ChainGraphStepsView,
  ChainGraphView,
  chainEdgeKey,
} from "./chain-graph";
import { ColumnWhyContent } from "./column-why-panel";
import {
  ALL_PRINCIPALS,
  PrincipalSelect,
  usePrincipal,
} from "./principal-context";
import { FilterBadge, MaskBadge } from "./status-badge";
import { asChainGraph } from "./trace-graph";
import { RowFilterFlow } from "./row-filter-flow";
import {
  UNIFIED_NODE_KINDS,
  focusUnifiedGraph,
  hideMaskedPrincipals,
  withSelectedColumn,
} from "./unified-graph";
import { CatalogTree, type CatalogEffect } from "./tree-explorer";
import { useViewerUrlState } from "./viewer-url-state";

const ALL_NODE_KINDS = new Set<string>(UNIFIED_NODE_KINDS);

type EffectDetailSelection = {
  key: string;
  node: ChainGraphNodeOut;
  graph: ChainGraphOut;
};

function RelationshipList({
  title,
  edges,
  nodeById,
  neighborOf,
  onSelect,
}: {
  title: string;
  edges: Array<GraphEdgeOut | ChainGraphEdgeOut>;
  nodeById: ReadonlyMap<string, { label: string }>;
  neighborOf: (edge: GraphEdgeOut | ChainGraphEdgeOut) => string;
  onSelect: (nodeId: string) => void;
}) {
  return (
    <section
      className="space-y-1.5"
      data-relationship-list={title.toLowerCase()}
    >
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </h4>
        <span className="text-[10px] text-muted-foreground">
          {edges.length}
        </span>
      </div>
      {edges.length === 0 ? (
        <p className="text-xs text-muted-foreground">None</p>
      ) : (
        <div className="space-y-1">
          {edges.map((edge, index) => {
            const nodeId = neighborOf(edge);
            const node = nodeById.get(nodeId);
            const codeSources = edge.code_sources ?? [];
            const codeLinkLabel =
              edge.kind === "tagged" ? "Open tag assignment" : "Open source";
            return (
              <div
                key={`${edge.source}-${edge.target}-${index}`}
                className="overflow-hidden rounded-md border"
              >
                <button
                  type="button"
                  onClick={() => onSelect(nodeId)}
                  className="w-full px-2.5 py-2 text-left hover:bg-muted/60"
                >
                  <span className="block break-all font-mono text-[11px] font-medium">
                    {node?.label ?? nodeId}
                  </span>
                  <span className="mt-0.5 block text-[10px] text-muted-foreground">
                    {edge.label} · {edge.kind}
                  </span>
                </button>
                {codeSources.length > 0 && (
                  <div className="space-y-1.5 border-t bg-muted/20 p-2">
                    {codeSources.map((source) => (
                      <div
                        key={source.securable}
                        className="flex items-center justify-between gap-2"
                      >
                        <div className="min-w-0 text-[10px] text-muted-foreground">
                          <span className="block font-medium text-foreground">
                            {source.inherited
                              ? `Inherited from ${source.securable_type}`
                              : `Direct tag on ${source.securable_type}`}
                          </span>
                          <span
                            className="block truncate font-mono"
                            title={source.securable}
                          >
                            {source.securable}
                          </span>
                          {source.source && (
                            <span
                              className="block truncate font-mono"
                              title={source.source}
                            >
                              {source.source}
                            </span>
                          )}
                        </div>
                        {source.github_url && (
                          <Button
                            asChild
                            variant="outline"
                            size="sm"
                            className="h-7 shrink-0 px-2 text-[10px]"
                          >
                            <a
                              data-edge-code-link
                              href={source.github_url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {codeLinkLabel} <ExternalLink />
                            </a>
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function UnifiedExplorer() {
  const { principal } = usePrincipal();
  return principal === ALL_PRINCIPALS ? (
    <AllPrincipalsExplorer />
  ) : (
    <PrincipalUnifiedExplorer />
  );
}

function AllPrincipalsExplorer() {
  const { search, update } = useViewerUrlState();
  const target = search.uTarget;
  const targetTable = target?.split(".").slice(0, 3).join(".");
  const targetColumn = target?.split(".").length === 4 ? target : undefined;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 xl:grid-cols-[260px_minmax(0,1fr)] xl:grid-rows-[auto_auto_1fr]">
        <div
          data-unified-panel="catalog"
          className="h-fit space-y-2 xl:sticky xl:top-24 xl:col-start-1 xl:row-span-3 xl:row-start-1"
        >
          <div className="space-y-1">
            <label className="block text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Principal
            </label>
            <PrincipalSelect includeAll className="w-full font-mono text-xs" />
          </div>
          <CatalogTree
            principal={undefined}
            selected={targetTable ?? null}
            selectedColumn={targetColumn}
            hideInaccessible={false}
            onHideInaccessibleChange={() => undefined}
            onSelect={(node) =>
              void update({
                uTarget: node.full_name,
                uNode: undefined,
                uSearch: undefined,
              })
            }
            onColumnSelect={(column) =>
              void update({
                uTarget: column,
                uNode: undefined,
                uSearch: undefined,
              })
            }
            compact
          />
        </div>

        {target ? (
          <Suspense fallback={<Skeleton className="h-[32rem] w-full" />}>
            <InverseAccessWorkspace target={target} />
          </Suspense>
        ) : (
          <Card className="xl:col-start-2">
            <CardContent className="flex min-h-80 flex-col items-center justify-center gap-3 text-center">
              <Users className="size-8 text-muted-foreground" />
              <div>
                <h3 className="font-medium">Select a table or column</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  The access graph stays hidden until you choose a securable from
                  the catalog tree.
                </p>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

function InverseAccessWorkspace({ target }: { target: string }) {
  const { search, update } = useViewerUrlState();
  const [effectDetail, setEffectDetail] =
    useState<EffectDetailSelection | null>(null);
  const { data } = useInverseAccessGraphSuspense({
    params: { securable: target },
  });
  const fullGraph = useMemo(
    () =>
      withSelectedColumn(
        data.data,
        data.data.target_type === "column" ? target : undefined,
      ),
    [data.data, target],
  );
  const hideMasked =
    fullGraph.target_type === "column" && search.uHideMasked !== false;
  const graph = useMemo(
    () => hideMaskedPrincipals(fullGraph, hideMasked),
    [fullGraph, hideMasked],
  );
  const chainGraph = useMemo(() => asChainGraph(graph), [graph]);
  const displayMode = search.mode ?? "graph";
  const effectsByPrincipal = useMemo(
    () =>
      new Map(
        graph.principal_effects.map((effect) => [effect.principal, effect]),
      ),
    [graph.principal_effects],
  );
  const nodeById = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph.nodes],
  );
  const activatableNodeIds = useMemo(
    () => new Set(graph.nodes.map((node) => node.id)),
    [graph.nodes],
  );
  const selectedNode = search.uNode ? nodeById.get(search.uNode) : undefined;
  const selectedEffect = selectedNode
    ? effectsByPrincipal.get(selectedNode.id)
    : undefined;
  const detailNode = effectDetail?.node ?? selectedNode;
  const detailEdges = effectDetail?.graph.edges ?? graph.edges;
  const detailNodeById = useMemo(
    () =>
      new Map(
        (effectDetail?.graph.nodes ?? graph.nodes).map((node) => [
          node.id,
          node,
        ]),
      ),
    [effectDetail, graph.nodes],
  );
  const detailEffect = effectDetail ? undefined : selectedEffect;
  const selectedRowFilterColumns =
    selectedEffect?.principal_kind === "group"
      ? []
      : (selectedEffect?.row_filter_policy_columns ??
        selectedEffect?.row_filter_columns ??
        []);
  const selectedMaskedColumns =
    selectedEffect?.principal_kind === "group"
      ? []
      : (selectedEffect?.mask_policy_columns ??
        selectedEffect?.masked_columns ??
        []);
  const incoming = detailNode
    ? detailEdges.filter((edge) => edge.target === detailNode.id)
    : [];
  const outgoing = detailNode
    ? detailEdges.filter((edge) => edge.source === detailNode.id)
    : [];
  const selectNode = (nodeId: string) => {
    setEffectDetail(null);
    void update({ uNode: nodeId, uSearch: undefined });
  };
  const selectDetailNode = (nodeId: string) => {
    if (!effectDetail) {
      selectNode(nodeId);
      return;
    }
    const node = effectDetail.graph.nodes.find(
      (candidate) => candidate.id === nodeId,
    );
    if (node) setEffectDetail({ ...effectDetail, node });
  };
  useEffect(() => setEffectDetail(null), [target]);
  const detailCodeLinkLabel =
    detailNode?.kind === "policy"
      ? "Open policy definition"
      : detailNode?.kind === "group"
        ? "Open group definition"
        : "Open source";

  return (
    <>
      <div
        data-unified-panel="graph"
        className="min-w-0 space-y-3 xl:col-start-2 xl:row-start-1"
      >
        <Card data-unified-access-graph className="min-w-0 overflow-hidden">
          <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0 p-4 pb-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm">
                <Network className="size-4" /> Who can access
              </CardTitle>
              <CardDescription className="mt-1 break-all font-mono text-xs">
                {target} · {graph.principal_effects.length} principals
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {fullGraph.target_type === "column" && (
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Switch
                    checked={hideMasked}
                    onCheckedChange={(checked) =>
                      void update({
                        uHideMasked: checked,
                        uNode: undefined,
                      })
                    }
                    aria-label="Hide principals with masked column access"
                  />
                  Hide masked
                </label>
              )}
              <div className="flex gap-1" aria-label="Access display mode">
                <Button
                  size="sm"
                  variant={displayMode === "graph" ? "default" : "outline"}
                  onClick={() => void update({ mode: "graph" })}
                >
                  Graph
                </Button>
                <Button
                  size="sm"
                  variant={displayMode === "steps" ? "default" : "outline"}
                  onClick={() => void update({ mode: "steps" })}
                >
                  Steps
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-3 pt-0">
            {graph.nodes.length === 0 ? (
              <div className="flex min-h-64 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
                No principals can read this {graph.target_type}.
              </div>
            ) : displayMode === "graph" ? (
              <ChainGraphView
                graph={chainGraph}
                ariaLabel={`Principals who can access ${target}`}
                activatableNodeIds={activatableNodeIds}
                onNodeActivate={selectNode}
                getNodeActivationLabel={(node) =>
                  `Inspect ${node.sublabel || node.kind} ${node.label}`
                }
                activationRole="button"
                selectedNodeId={selectedNode?.id}
                onCanvasActivate={() => {
                  setEffectDetail(null);
                  void update({ uNode: undefined });
                }}
                optimizeNodeOrder
              />
            ) : (
              <ChainGraphStepsView
                graph={chainGraph}
                activatableNodeIds={activatableNodeIds}
                onNodeActivate={selectNode}
                selectedNodeId={selectedNode?.id}
              />
            )}
          </CardContent>
        </Card>
        {selectedEffect && (
          <PrincipalEffectDetails
            effect={selectedEffect}
            table={target.split(".").slice(0, 3).join(".")}
            selectedDetail={effectDetail}
            onNodeActivate={(selection) => setEffectDetail(selection)}
          />
        )}
      </div>

      <Card
        data-unified-panel="details"
        className="h-fit xl:col-start-2 xl:row-start-2"
      >
        <CardHeader className="p-4 pb-3">
          <CardTitle className="text-sm">Node details</CardTitle>
          <CardDescription className="text-xs">
            Inspect relationships without changing views.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 p-4 pt-0">
          {detailNode ? (
            <>
              <div className="space-y-2">
                <Badge variant="outline" className="uppercase">
                  {detailEffect?.principal_kind ?? detailNode.kind}
                </Badge>
                <h3 className="break-all font-mono text-sm font-semibold">
                  {detailNode.label}
                </h3>
                {detailNode.id !== detailNode.label && (
                  <p className="break-all font-mono text-[10px] text-muted-foreground">
                    {detailNode.id}
                  </p>
                )}
                {detailNode.source && detailNode.kind !== "table" && (
                  <p className="break-all font-mono text-[10px] text-muted-foreground">
                    {detailNode.source}
                  </p>
                )}
              </div>

              {detailEffect && (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    {detailEffect.principal_kind !== "group" &&
                      detailEffect.row_filter_targeted && (
                        <FilterBadge
                          filtered={detailEffect.row_filtered}
                          targeted
                        />
                      )}
                    {detailEffect.principal_kind !== "group" &&
                      detailEffect.mask_targeted && (
                        <MaskBadge
                          masked={detailEffect.masked}
                          targeted
                        />
                      )}
                    {detailEffect.principal_kind === "group" && (
                      <span className="text-xs text-muted-foreground">
                        Group access path
                      </span>
                    )}
                    {!detailEffect.row_filter_targeted &&
                      detailEffect.principal_kind !== "group" &&
                      !detailEffect.mask_targeted && (
                        <span className="text-xs text-muted-foreground">
                          Unfiltered and unmasked
                        </span>
                      )}
                  </div>
                  {selectedRowFilterColumns.length > 0 && (
                    <EffectColumnList
                      label={
                        detailEffect.row_filtered
                          ? "Row filter columns"
                          : "Row filter policy columns"
                      }
                      columns={selectedRowFilterColumns}
                    />
                  )}
                  {selectedMaskedColumns.length > 0 && (
                    <EffectColumnList
                      label={
                        detailEffect.masked
                          ? "Masked columns"
                          : "Mask policy columns"
                      }
                      columns={selectedMaskedColumns}
                    />
                  )}
                </div>
              )}

              <RelationshipList
                title="Incoming"
                edges={incoming}
                nodeById={detailNodeById}
                neighborOf={(edge) => edge.source}
                onSelect={selectDetailNode}
              />
              <RelationshipList
                title="Outgoing"
                edges={outgoing}
                nodeById={detailNodeById}
                neighborOf={(edge) => edge.target}
                onSelect={selectDetailNode}
              />

              {detailNode.github_url &&
                detailNode.kind !== "user" && (
                  <Button
                    asChild
                    variant="outline"
                    size="sm"
                    className="w-full"
                  >
                    <a
                      data-node-code-link
                      href={detailNode.github_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {detailCodeLinkLabel} <ExternalLink />
                    </a>
                  </Button>
                )}
            </>
          ) : (
            <div className="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">
              Select any graph node to inspect it here.
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
}

function EffectColumnList({
  label,
  columns,
}: {
  label: string;
  columns: string[];
}) {
  return (
    <section className="space-y-1">
      <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </h4>
      {columns.map((column) => (
        <div key={column} className="break-all font-mono text-[11px]">
          {column}
        </div>
      ))}
    </section>
  );
}

function PrincipalEffectWhy({
  effect,
  target,
  focus,
  selectedDetail,
  onNodeActivate,
}: {
  effect: PrincipalEffectOut;
  target: string;
  focus: "filter" | "mask";
  selectedDetail: EffectDetailSelection | null;
  onNodeActivate: (selection: EffectDetailSelection) => void;
}) {
  const graphRef = useRef<ChainGraphOut | null>(null);
  const key = `${focus}:${target}`;
  return (
    <div data-principal-effect-why={focus} className="space-y-2">
      <h4 className="text-sm font-medium">
        {focus === "filter" ? "Row filter Why" : "Mask Why"}
      </h4>
      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        {focus === "filter" ? (
          <RowFilterFlow
            principal={effect.principal}
            table={target}
            selectedNodeId={selectedDetail?.key === key ? selectedDetail.node.id : undefined}
            onNodeActivate={(node) => {
              if (graphRef.current) {
                onNodeActivate({ key, node, graph: graphRef.current });
              }
            }}
            onGraphChange={(graph) => {
              graphRef.current = graph;
            }}
          />
        ) : (
          <ColumnWhyContent
            principal={effect.principal}
            column={target}
            focus="mask"
            inline
            selectedNodeId={selectedDetail?.key === key ? selectedDetail.node.id : undefined}
            onNodeActivate={(node) => {
              if (graphRef.current) {
                onNodeActivate({ key, node, graph: graphRef.current });
              }
            }}
            onGraphChange={(graph) => {
              graphRef.current = graph;
            }}
          />
        )}
      </Suspense>
    </div>
  );
}

function PrincipalEffectDetails({
  effect,
  table,
  selectedDetail,
  onNodeActivate,
}: {
  effect: PrincipalEffectOut;
  table: string;
  selectedDetail: EffectDetailSelection | null;
  onNodeActivate: (selection: EffectDetailSelection) => void;
}) {
  const rowFilterColumns =
    effect.principal_kind === "group"
      ? []
      : (effect.row_filter_policy_columns ?? effect.row_filter_columns ?? []);
  const maskedColumns =
    effect.principal_kind === "group"
      ? []
      : (effect.mask_policy_columns ?? effect.masked_columns ?? []);
  const hasEffects = rowFilterColumns.length > 0 || maskedColumns.length > 0;
  return (
    <Card data-all-principal-effects>
      <CardHeader className="p-4 pb-3">
        <CardTitle className="text-sm">Access effects</CardTitle>
        <CardDescription className="break-all font-mono text-xs">
          {effect.principal}
        </CardDescription>
      </CardHeader>
      <CardContent className="p-4 pt-0">
        {hasEffects ? (
          <div data-principal-effect-list className="space-y-4">
            {rowFilterColumns.length > 0 && (
              <PrincipalEffectWhy
                key={`filter:${table}`}
                effect={effect}
                target={table}
                focus="filter"
                selectedDetail={selectedDetail}
                onNodeActivate={onNodeActivate}
              />
            )}
            {maskedColumns.map((column) => (
              <PrincipalEffectWhy
                key={`mask:${column}`}
                effect={effect}
                target={column}
                focus="mask"
                selectedDetail={selectedDetail}
                onNodeActivate={onNodeActivate}
              />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {effect.principal_kind === "group"
              ? "This group contributes an access path. Masking is evaluated for users and service principals."
              : "This principal reads the selection without row filtering or masking."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function PrincipalUnifiedExplorer() {
  const { principal } = usePrincipal();
  const { search, update } = useViewerUrlState();
  const { data } = useAccessGraphSuspense({ params: { principal } });
  const { data: columnsData } = useColumnsForPrincipalSuspense({
    params: { principal, filter: "all" },
  });
  const selectedColumn =
    search.uTarget?.split(".").length === 4
      ? search.uTarget
      : search.uEffectColumn;
  const selectedColumnTable = selectedColumn
    ?.split(".")
    .slice(0, 3)
    .join(".");
  const selectedColumnVerdict = columnsData.data.find(
    (column) => column.column_full_name === selectedColumn,
  );
  const graph = useMemo(
    () =>
      withSelectedColumn(data.data, selectedColumn, {
        mask_targeted: selectedColumnVerdict?.mask_targeted,
        masked: selectedColumnVerdict?.masked,
      }),
    [
      data.data,
      selectedColumn,
      selectedColumnVerdict?.mask_targeted,
      selectedColumnVerdict?.masked,
    ],
  );
  const displayMode = search.mode ?? "graph";
  const query = search.uSearch ?? "";
  const nodeById = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph.nodes],
  );
  const selectedNode = search.uNode ? nodeById.get(search.uNode) : undefined;
  const [inlineDetailNode, setInlineDetailNode] =
    useState<ChainGraphNodeOut | null>(null);
  const [inlineGraph, setInlineGraph] = useState<ChainGraphOut | null>(null);
  const detailNode = inlineDetailNode ?? selectedNode;
  const inlineNodeById = useMemo(
    () => new Map((inlineGraph?.nodes ?? []).map((node) => [node.id, node])),
    [inlineGraph],
  );
  const effectAccessPathNodeIds = useMemo(() => {
    const nodeIds = new Set<string>();
    if (!search.uEffectTable) return nodeIds;

    const incomingByTarget = new Map<string, GraphEdgeOut[]>();
    for (const edge of graph.edges) {
      const incoming = incomingByTarget.get(edge.target) ?? [];
      incoming.push(edge);
      incomingByTarget.set(edge.target, incoming);
    }

    const queue = [search.uEffectTable];
    nodeIds.add(search.uEffectTable);
    while (queue.length > 0) {
      const nodeId = queue.shift()!;
      for (const edge of incomingByTarget.get(nodeId) ?? []) {
        if (nodeIds.has(edge.source)) continue;
        nodeIds.add(edge.source);
        queue.push(edge.source);
      }
    }
    return nodeIds;
  }, [graph.edges, search.uEffectTable]);
  const focusedGraph = useMemo(
    () => focusUnifiedGraph(graph, query, ALL_NODE_KINDS),
    [graph, query],
  );
  const displayedGraph = selectedNode ? graph : focusedGraph;
  const chainGraph = useMemo(
    () => asChainGraph(displayedGraph),
    [displayedGraph],
  );
  const detailEdges = inlineDetailNode
    ? (inlineGraph?.edges ?? [])
    : graph.edges;
  const detailNodeById = inlineDetailNode ? inlineNodeById : nodeById;
  const incoming = detailNode
    ? detailEdges.filter((edge) => edge.target === detailNode.id)
    : [];
  const outgoing = detailNode
    ? detailEdges.filter((edge) => edge.source === detailNode.id)
    : [];
  const visibleNodeIds = useMemo(
    () => new Set(displayedGraph.nodes.map((node) => node.id)),
    [displayedGraph.nodes],
  );
  const highlightedPath = useMemo(() => {
    const nodeIds = new Set<string>();
    const edgeKeys = new Set<string>();
    if (!selectedNode) return { nodeIds, edgeKeys };

    const incomingEdges = new Map<string, typeof chainGraph.edges>();
    const outgoingEdges = new Map<string, typeof chainGraph.edges>();
    for (const edge of chainGraph.edges) {
      const edges = incomingEdges.get(edge.target) ?? [];
      edges.push(edge);
      incomingEdges.set(edge.target, edges);
      const nextEdges = outgoingEdges.get(edge.source) ?? [];
      nextEdges.push(edge);
      outgoingEdges.set(edge.source, nextEdges);
    }
    nodeIds.add(selectedNode.id);

    const walk = (
      adjacency: Map<string, typeof chainGraph.edges>,
      nextNode: (edge: (typeof chainGraph.edges)[number]) => string,
    ) => {
      const seen = new Set([selectedNode.id]);
      const queue = [selectedNode.id];
      while (queue.length > 0) {
        const nodeId = queue.shift()!;
        for (const edge of adjacency.get(nodeId) ?? []) {
          edgeKeys.add(chainEdgeKey(edge));
          const next = nextNode(edge);
          nodeIds.add(next);
          if (seen.has(next)) continue;
          seen.add(next);
          queue.push(next);
        }
      }
    };
    walk(incomingEdges, (edge) => edge.source);
    walk(outgoingEdges, (edge) => edge.target);
    return { nodeIds, edgeKeys };
  }, [chainGraph.edges, selectedNode]);
  const inlineWhyRef = useRef<HTMLDivElement>(null);
  const previousPrincipal = useRef(principal);

  const clearSelection = (clearSearch = false, closeInlineWhy = false) => {
    setInlineDetailNode(null);
    if (closeInlineWhy) setInlineGraph(null);
    void update({
      uNode: undefined,
      uSearch: clearSearch ? undefined : search.uSearch,
      uEffect: closeInlineWhy ? undefined : search.uEffect,
      uEffectTable: closeInlineWhy ? undefined : search.uEffectTable,
      uEffectColumn: closeInlineWhy ? undefined : search.uEffectColumn,
      uTarget:
        closeInlineWhy || !search.uEffectColumn ? undefined : search.uTarget,
    });
  };

  // The principal picker clears the URL selection itself, so a link that sets a
  // principal and a node together (a drift warning) keeps the node; a principal
  // change only resets the local panels here.
  useEffect(() => {
    if (previousPrincipal.current === principal) return;
    previousPrincipal.current = principal;
    setInlineDetailNode(null);
    setInlineGraph(null);
  }, [principal]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !search.why) clearSelection(true);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  });

  useEffect(() => {
    if (
      !search.uEffect ||
      (search.uEffect === "filter"
        ? !search.uEffectTable
        : !search.uEffectColumn)
    ) {
      return;
    }
    inlineWhyRef.current?.scrollIntoView({ block: "nearest" });
  }, [search.uEffect, search.uEffectColumn, search.uEffectTable]);

  const selectNode = (nodeId: string) => {
    setInlineDetailNode(null);
    const selectingDifferentTable =
      nodeById.get(nodeId)?.kind === "table" &&
      Boolean(search.uEffectTable) &&
      nodeId !== search.uEffectTable;
    const keepInlineWhy =
      !selectingDifferentTable &&
      Boolean(search.uEffect && search.uEffectTable) &&
      (effectAccessPathNodeIds.has(nodeId) ||
        Boolean(inlineGraph?.nodes.some((node) => node.id === nodeId)));
    if (!keepInlineWhy) setInlineGraph(null);
    void update({
      uNode: nodeId,
      uSearch: undefined,
      uEffect: keepInlineWhy ? search.uEffect : undefined,
      uEffectTable: keepInlineWhy ? search.uEffectTable : undefined,
      uEffectColumn: keepInlineWhy ? search.uEffectColumn : undefined,
      uTarget: keepInlineWhy ? search.uTarget : undefined,
    });
  };

  const selectInlineNode = (nodeId: string) => {
    const node = inlineNodeById.get(nodeId);
    if (node) setInlineDetailNode(node);
  };

  const selectEffect = (table: string, effect: CatalogEffect) => {
    setInlineDetailNode(null);
    const sameEffect =
      search.uEffect === effect && search.uEffectTable === table;
    setInlineGraph(null);
    void update({
      uNode: table,
      uSearch: undefined,
      uEffect: sameEffect ? undefined : effect,
      uEffectTable: sameEffect ? undefined : table,
      uEffectColumn: undefined,
      uTarget: undefined,
    });
  };

  const detailCodeLinkLabel =
    detailNode?.kind === "policy"
      ? "Open policy definition"
      : detailNode?.kind === "group"
        ? "Open group definition"
        : "Open source";

  return (
    <div className="space-y-3">
      <div className="grid gap-3 xl:grid-cols-[260px_minmax(0,1fr)] xl:grid-rows-[auto_auto_1fr]">
        <div
          data-unified-panel="catalog"
          className="h-fit space-y-2 xl:sticky xl:top-24 xl:col-start-1 xl:row-span-3 xl:row-start-1"
        >
          <div className="space-y-1">
            <label className="block text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Principal
            </label>
            <PrincipalSelect includeAll className="w-full font-mono text-xs" />
          </div>
          <CatalogTree
            key={principal}
            principal={principal}
            selected={
              selectedNode?.kind === "table"
                ? selectedNode.id
                : (selectedColumnTable ?? null)
            }
            selectedColumn={selectedColumn}
            hideInaccessible={search.hide !== false}
            onHideInaccessibleChange={(checked) =>
              void update({ hide: checked })
            }
            onSelect={(node) => {
              setInlineDetailNode(null);
              setInlineGraph(null);
              void update({
                uNode: node.full_name,
                uSearch: undefined,
                uTarget: undefined,
                uEffect: undefined,
                uEffectTable: undefined,
                uEffectColumn: undefined,
              });
            }}
            activeEffect={search.uEffect}
            effectTable={search.uEffectTable}
            effectColumn={search.uEffectColumn}
            onEffect={selectEffect}
            onEffectColumn={(column) => {
              setInlineDetailNode(null);
              setInlineGraph(null);
              void update({
                uNode: column,
                uTarget: column,
                uEffectColumn: column,
              });
            }}
            onColumnSelect={(column, effect) => {
              setInlineDetailNode(null);
              setInlineGraph(null);
              const table = column.split(".").slice(0, 3).join(".");
              void update({
                uNode: column,
                uTarget: column,
                uSearch: undefined,
                uEffect: effect,
                uEffectTable: effect ? table : undefined,
                uEffectColumn: effect ? column : undefined,
              });
            }}
            compact
          />
        </div>

        <div
          data-unified-panel="graph"
          className="min-w-0 space-y-3 xl:col-start-2 xl:row-start-1"
        >
          <Card data-unified-access-graph className="min-w-0 overflow-hidden">
            <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0 p-4 pb-3">
              <div>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Network className="size-4" /> Access graph
                </CardTitle>
                <CardDescription className="mt-1 text-xs">
                  {displayedGraph.nodes.length} of {graph.nodes.length} nodes ·{" "}
                  {displayedGraph.edges.length} relationships
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex gap-1" aria-label="Access display mode">
                  <Button
                    size="sm"
                    variant={displayMode === "graph" ? "default" : "outline"}
                    onClick={() => void update({ mode: "graph" })}
                  >
                    Graph
                  </Button>
                  <Button
                    size="sm"
                    variant={displayMode === "steps" ? "default" : "outline"}
                    onClick={() => void update({ mode: "steps" })}
                  >
                    Steps
                  </Button>
                </div>
                <div className="relative w-60 max-w-full">
                  <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                  <input
                    id="unified-search"
                    type="search"
                    value={query}
                    onChange={(event) =>
                      void update(
                        { uSearch: event.target.value || undefined },
                        { replace: true },
                      )
                    }
                    placeholder="Find table, tag, policy…"
                    className="h-9 w-full rounded-md border border-input bg-background pl-8 pr-3 text-xs outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-3 pt-0">
              {displayedGraph.nodes.length <= 1 && query ? (
                <div className="flex min-h-80 items-center justify-center rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
                  No graph elements match “{query}”.
                </div>
              ) : displayMode === "graph" ? (
                <ChainGraphView
                  graph={chainGraph}
                  ariaLabel={`Unified access graph for ${principal}`}
                  activatableNodeIds={visibleNodeIds}
                  onNodeActivate={selectNode}
                  onNodeEffectActivate={(nodeId, effect) => {
                    if (effect === "filter") {
                      selectEffect(nodeId, "filter");
                      return;
                    }
                    const node = nodeById.get(nodeId);
                    if (node?.kind !== "column") return;
                    const table = nodeId.split(".").slice(0, 3).join(".");
                    setInlineDetailNode(null);
                    setInlineGraph(null);
                    void update({
                      uNode: nodeId,
                      uTarget: nodeId,
                      uSearch: undefined,
                      uEffect: "mask",
                      uEffectTable: table,
                      uEffectColumn: nodeId,
                    });
                  }}
                  getNodeActivationLabel={(node) =>
                    `Inspect ${node.sublabel ?? node.kind} ${node.label}`
                  }
                  activationRole="button"
                  selectedNodeId={selectedNode?.id}
                  highlightedNodeIds={highlightedPath.nodeIds}
                  highlightedEdgeKeys={highlightedPath.edgeKeys}
                  onCanvasActivate={() => clearSelection()}
                  optimizeNodeOrder
                />
              ) : (
                <ChainGraphStepsView
                  graph={chainGraph}
                  activatableNodeIds={visibleNodeIds}
                  onNodeActivate={selectNode}
                  selectedNodeId={selectedNode?.id}
                />
              )}
            </CardContent>
          </Card>
          {search.uEffect &&
            search.uEffectTable &&
            (search.uEffect === "filter" || search.uEffectColumn) && (
            <Card ref={inlineWhyRef} data-unified-inline-why>
              <CardHeader className="flex-row items-start justify-between gap-3 space-y-0 p-4 pb-3">
                <div>
                  <CardTitle className="text-sm">
                    {search.uEffect === "filter"
                      ? "Row filter Why"
                      : "Mask Why"}
                  </CardTitle>
                  <CardDescription className="mt-1 break-all font-mono text-xs">
                    {principal} ×{" "}
                    {search.uEffect === "filter"
                      ? search.uEffectTable
                      : search.uEffectColumn}
                  </CardDescription>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={`Close inline ${search.uEffect === "filter" ? "row filter" : "column"} Why`}
                  title="Close"
                  onClick={() => {
                    setInlineDetailNode(null);
                    setInlineGraph(null);
                    void update({
                      uNode: search.uEffectTable,
                      uTarget: undefined,
                      uEffect: undefined,
                      uEffectTable: undefined,
                      uEffectColumn: undefined,
                    });
                  }}
                >
                  <X />
                </Button>
              </CardHeader>
              <CardContent className="p-4 pt-0">
                <Suspense fallback={<Skeleton className="h-48 w-full" />}>
                  {search.uEffect === "filter" ? (
                    <RowFilterFlow
                      principal={principal}
                      table={search.uEffectTable}
                      mode={search.mode ?? "graph"}
                      selectedNodeId={inlineDetailNode?.id}
                      onNodeActivate={setInlineDetailNode}
                      onGraphChange={setInlineGraph}
                    />
                  ) : (
                    <ColumnWhyContent
                      principal={principal}
                      column={search.uEffectColumn!}
                      focus="mask"
                      inline
                      selectedNodeId={inlineDetailNode?.id}
                      onNodeActivate={setInlineDetailNode}
                      onGraphChange={setInlineGraph}
                    />
                  )}
                </Suspense>
              </CardContent>
            </Card>
          )}
        </div>

        <Card
          data-unified-panel="details"
          className="h-fit xl:col-start-2 xl:row-start-2"
        >
          <CardHeader className="p-4 pb-3">
            <CardTitle className="text-sm">Node details</CardTitle>
            <CardDescription className="text-xs">
              Inspect relationships without changing views.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 p-4 pt-0">
            {!detailNode ? (
              <div className="rounded-md border border-dashed p-6 text-center text-xs text-muted-foreground">
                Select any graph node to inspect it here.
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="uppercase">
                      {detailNode.kind}
                    </Badge>
                  </div>
                  <h3 className="break-all font-mono text-sm font-semibold">
                    {detailNode.label}
                  </h3>
                  {detailNode.id !== detailNode.label && (
                    <p className="break-all font-mono text-[10px] text-muted-foreground">
                      {detailNode.id}
                    </p>
                  )}
                  {detailNode.source && detailNode.kind !== "table" && (
                    <p className="break-all font-mono text-[10px] text-muted-foreground">
                      {detailNode.source}
                    </p>
                  )}
                </div>

                <RelationshipList
                  title="Incoming"
                  edges={incoming}
                  nodeById={detailNodeById}
                  neighborOf={(edge) => edge.source}
                  onSelect={inlineDetailNode ? selectInlineNode : selectNode}
                />
                <RelationshipList
                  title="Outgoing"
                  edges={outgoing}
                  nodeById={detailNodeById}
                  neighborOf={(edge) => edge.target}
                  onSelect={inlineDetailNode ? selectInlineNode : selectNode}
                />

                {detailNode.github_url &&
                  detailNode.kind !== "user" && (
                    <Button
                      asChild
                      variant="outline"
                      size="sm"
                      className="w-full"
                    >
                      <a
                        data-node-code-link
                        href={detailNode.github_url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {detailCodeLinkLabel} <ExternalLink />
                      </a>
                    </Button>
                  )}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
