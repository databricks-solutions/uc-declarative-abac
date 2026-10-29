import { Suspense, useMemo, useState } from "react";
import { ChevronsDown, ChevronsUp } from "lucide-react";
import {
  useAccessGraphSuspense,
  type ChainGraphOut,
  type GraphEdgeOut,
  type GraphOut,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ChainGraphView } from "./chain-graph";
import { ColumnWhyPanel } from "./column-why-panel";
import { PrincipalSelect, usePrincipal } from "./principal-context";
import { useViewerUrlState } from "./viewer-url-state";
import { WhyPanel } from "./why-panel";

function visibleGraph(
  graph: GraphOut,
  principal: string,
  expanded: Set<string>,
): GraphOut {
  const outgoing = new Map<string, GraphEdgeOut[]>();
  for (const edge of graph.edges) {
    const edges = outgoing.get(edge.source) ?? [];
    edges.push(edge);
    outgoing.set(edge.source, edges);
  }

  const visible = new Set([principal]);
  const queue = [principal];
  while (queue.length > 0) {
    const source = queue.shift()!;
    if (!expanded.has(source)) continue;
    for (const edge of outgoing.get(source) ?? []) {
      if (!visible.has(edge.target)) {
        visible.add(edge.target);
        queue.push(edge.target);
      }
    }
  }

  return {
    ...graph,
    nodes: graph.nodes.filter((node) => visible.has(node.id)),
    edges: graph.edges.filter(
      (edge) => visible.has(edge.source) && visible.has(edge.target),
    ),
  };
}

const SECURABLE_KINDS = new Set(["catalog", "schema", "table"]);

// Grant sources are labelled by where they are defined: an ABAC grant policy in
// the config, or a privilege granted outside it.
const SUBLABELS: Record<string, string> = {
  policy: "ABAC grant policy",
  manual: "manual grant",
};

export function asChainGraph(graph: GraphOut): ChainGraphOut {
  const groupLayers = new Map<string, number>(
    graph.nodes
      .filter((node) => node.kind === "user")
      .map((node) => [node.id, 0]),
  );
  groupLayers.set(graph.principal, 0);
  const membershipEdges = graph.edges.filter(
    (edge) => edge.kind === "membership",
  );
  for (let pass = 0; pass < graph.nodes.length; pass += 1) {
    let changed = false;
    for (const edge of membershipEdges) {
      const sourceLayer = groupLayers.get(edge.source);
      if (sourceLayer === undefined) continue;
      const nextLayer = sourceLayer + 1;
      if ((groupLayers.get(edge.target) ?? -1) < nextLayer) {
        groupLayers.set(edge.target, nextLayer);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const maxGroupLayer = Math.max(
    0,
    ...graph.nodes
      .filter((node) => node.kind === "group")
      .map((node) => groupLayers.get(node.id) ?? 1),
  );
  const layerOf = (node: GraphOut["nodes"][number]) => {
    if (node.kind === "user") return 0;
    if (node.kind === "group") return groupLayers.get(node.id) ?? 1;
    if (node.kind === "policy" || node.kind === "manual") return maxGroupLayer + 1;
    if (node.kind === "tag") return maxGroupLayer + 2;
    if (node.kind === "column") return maxGroupLayer + 4;
    return maxGroupLayer + 3;
  };
  return {
    principal: graph.principal,
    securable: "grant exploration",
    nodes: graph.nodes.map((node) => ({
      id: node.id,
      kind: SECURABLE_KINDS.has(node.kind) ? "securable" : node.kind,
      label: node.label,
      layer: layerOf(node),
      sublabel: SUBLABELS[node.kind] ?? node.kind,
      source: node.source,
      github_url: node.github_url,
      effect_principal: node.effect_principal,
      mask_targeted: node.mask_targeted,
      masked: node.masked,
      row_filter_targeted: node.row_filter_targeted,
      row_filtered: node.row_filtered,
    })),
    edges: graph.edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      label: edge.label,
      kind: edge.kind === "membership" ? "member" : edge.kind,
    })),
  };
}

function TraceGraphContent({
  principal,
  onTableWhy,
}: {
  principal: string;
  onTableWhy: (table: string) => void;
}) {
  const { data } = useAccessGraphSuspense({ params: { principal } });
  const graph = data.data;
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(graph.edges.map((edge) => edge.source)),
  );
  const shownGraph = useMemo(
    () => asChainGraph(visibleGraph(graph, principal, expanded)),
    [expanded, graph, principal],
  );
  const expandable = useMemo(
    () => new Set(graph.edges.map((edge) => edge.source)),
    [graph.edges],
  );
  const tables = useMemo(
    () =>
      new Set(
        graph.nodes
          .filter((node) => node.kind === "table")
          .map((node) => node.id),
      ),
    [graph.nodes],
  );

  const toggle = (nodeId: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="Expand all"
            aria-label="Expand all grant paths"
            onClick={() => setExpanded(new Set(expandable))}
          >
            <ChevronsDown />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="Collapse all"
            aria-label="Collapse all grant paths"
            onClick={() => setExpanded(new Set())}
          >
            <ChevronsUp />
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          Follow direct membership, parent groups, grant policies, matching
          tags, and tables.
        </p>
      </div>
      <ChainGraphView
        graph={shownGraph}
        ariaLabel={`Grant exploration graph for ${principal}`}
        hideEdgeKinds={["cascade", "inherit"]}
        expandableNodeIds={expandable}
        expandedNodeIds={expanded}
        onNodeToggle={toggle}
        activatableNodeIds={tables}
        onNodeActivate={onTableWhy}
        optimizeNodeOrder
      />
    </div>
  );
}

export function TraceGraph() {
  const { principal } = usePrincipal();
  const { search, openWhy, closeWhy } = useViewerUrlState();
  const tableWhy = search.why === "table" ? search.target ?? null : null;
  const columnWhy = search.why === "column" ? search.target ?? null : null;
  const whyPrincipal = search.wp ?? principal;

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">Principal</label>
        <Suspense fallback={<Skeleton className="h-9 w-72" />}>
          <PrincipalSelect />
        </Suspense>
      </div>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <TraceGraphContent
          key={principal}
          principal={principal}
          onTableWhy={(table) => void openWhy("table", table)}
        />
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
        principal={whyPrincipal}
        column={columnWhy}
        onClose={closeWhy}
      />
    </div>
  );
}
