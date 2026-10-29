import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { EyeOff, ListFilter } from "lucide-react";
import {
  useExplainColumnGraphSuspense,
  useExplainGraphSuspense,
  type ChainGraphNodeOut,
  type ChainGraphOut,
} from "@/lib/api";
import { useSkin } from "./skin-context";

/** Why-chain graph (per the deck): every node on the path from a user/SP to
 * the securable — user → subgroup → group → policy → tag → securable — plus
 * containment edges (catalog ⊃ schema ⊃ table ⊃ column) for inheritance.
 * Layers come from the backend; this renders a generic layered DAG.
 *
 * ChainGraphView is presentational (takes a graph + options); ChainGraph and
 * ColumnChainGraph are thin data wrappers. */

const KIND_COLOR: Record<string, string> = {
  user: "var(--graph-user)",
  group: "var(--graph-group)",
  policy: "var(--graph-policy)",
  manual: "var(--graph-manual)",
  tag: "var(--graph-tag)",
  securable: "var(--graph-securable)",
  column: "var(--graph-securable)",
  constant: "var(--graph-constant)",
};

const EDGE_STYLE: Record<string, { stroke: string; dash?: string; arrow?: boolean }> = {
  member: { stroke: "var(--graph-user)" },
  to: { stroke: "var(--graph-group)" },
  matches: { stroke: "var(--graph-tag)" },
  tagged: { stroke: "var(--graph-tag)", dash: "4 3" },
  grant: { stroke: "var(--graph-securable)", arrow: true },
  effect: { stroke: "var(--graph-effect)", arrow: true },
  // effects radiating from the tag-matched securable (the anchor):
  cascade: { stroke: "var(--graph-securable)", dash: "6 4", arrow: true },
  inherit: { stroke: "var(--graph-securable)", dash: "6 4", arrow: true },
  contains: { stroke: "currentColor", dash: "2 4", arrow: true },
  argument: { stroke: "var(--graph-constant)", dash: "3 2", arrow: true },
  // divergence from the config: a grant made outside it, and a policy grant UC
  // does not hold. Their colours carry meaning, so the Databricks skin keeps them.
  manual_grant: { stroke: "var(--graph-manual)", dash: "1 3", arrow: true },
  drift: { stroke: "var(--graph-drift)", dash: "6 3", arrow: true },
};

const MEANINGFUL_EDGE_KINDS = new Set(["manual_grant", "drift"]);

// Legend names for node kinds whose raw kind would be unclear.
const KIND_LABEL: Record<string, string> = {
  policy: "ABAC policy",
  manual: "manual grant (not in config)",
};

const NODE_MIN_W = 100;
const NODE_MAX_W = 180;
const NARROW_NODE_MAX_W = 160;
const NODE_H = 48;
const COL_GAP = 72;
// When a graph is wider than its canvas, compact it (text size stays fixed):
// trim long labels first, then tighten gaps, then trim labels further.
const FIT_STEPS: { cap: number; gap: number }[] = [
  { cap: 170, gap: COL_GAP },
  { cap: 160, gap: COL_GAP },
  { cap: 150, gap: COL_GAP },
  { cap: 150, gap: 64 },
  { cap: 150, gap: 56 },
  { cap: 140, gap: 56 },
  { cap: 130, gap: 56 },
  { cap: 120, gap: 56 },
];
const LEFT_PAD = 16;
const ROW_GAP = 30;
// Sized for reading on a shared screen: label/sublabel/edge-label font sizes,
// and the approximate monospace advance of one label character.
const LABEL_FONT = 12;
const LABEL_CHAR_W = 7.3;
const SUBLABEL_FONT = 10;
// Uppercase with 0.06em tracking, so wider per character than the label.
const SUBLABEL_CHAR_W = 7;
const EDGE_LABEL_FONT = 9;
const EDGE_LABEL_CHAR_W = 5.6;
// Fixed render scale: text stays the same on-screen size whatever the graph's
// size. Graphs wider than the canvas scroll horizontally instead of shrinking.
const GRAPH_SCALE = 0.867;
const BADGE_SIZE = 24;
const BADGE_Y = (NODE_H - BADGE_SIZE) / 2;
const TOP_PAD = 64; // room for edge labels that arc above the top row
const RIGHT_PAD = 12;
const SAME_LAYER_CONTAINS_BULGE = 18;
const SAME_LAYER_EDGE_BULGE = 22;

type Positioned = ChainGraphNodeOut & { x: number; y: number; width: number };

const ROW_PITCH = NODE_H + ROW_GAP;

export function chainEdgeKey(edge: {
  source: string;
  target: string;
  kind: string;
  label: string;
}) {
  return `${edge.source}\u0000${edge.target}\u0000${edge.kind}\u0000${edge.label}`;
}

// Vertical order within the securable column: CATALOG on top, then SCHEMA,
// then TABLE, then COLUMN — so containment reads top→bottom. Everything else
// keeps a stable rank and falls back to id ordering within a layer.
const SECURABLE_RANK: Record<string, number> = {
  catalog: 0,
  schema: 1,
  table: 2,
  column: 3,
};

function layoutLayers(
  nodes: ChainGraphNodeOut[],
  edges: { source: string; target: string; kind?: string; label?: string }[],
  nodeWidthCap: number,
  optimizeNodeOrder = false,
  maxWidth?: number,
): Map<string, Positioned> {
  const layers = new Map<number, ChainGraphNodeOut[]>();
  for (const n of nodes) {
    (layers.get(n.layer) ?? layers.set(n.layer, []).get(n.layer)!).push(n);
  }
  const layerIndexes = Array.from(layers.keys()).sort((a, b) => a - b);
  const maxRows = Math.max(...Array.from(layers.values()).map((l) => l.length));
  const naturalWidths = new Map(
    nodes.map((node) => [
      node.id,
      Math.max(
        NODE_MIN_W,
        Math.ceil(node.label.length * LABEL_CHAR_W + 18),
        Math.ceil((node.sublabel?.length ?? 0) * SUBLABEL_CHAR_W + 18),
      ),
    ]),
  );

  const rank = (n: ChainGraphNodeOut) => SECURABLE_RANK[n.sublabel ?? ""] ?? 99;

  // Each node gets a y-slot. Securables retain CATALOG→SCHEMA→TABLE order;
  // other layers can follow the barycenter of their incoming, left-hand
  // neighbors so parallel paths remain level and do not cross.
  const cols = new Map<number, ChainGraphNodeOut[]>();
  const slot = new Map<string, number>();
  for (const layer of layerIndexes) {
    const col = [...layers.get(layer)!].sort(
      (a, b) => rank(a) - rank(b) || a.id.localeCompare(b.id),
    );
    cols.set(layer, col);
    const base = (maxRows - col.length) / 2;
    col.forEach((n, i) => slot.set(n.id, base + i));
  }

  const nodeLayer = new Map(nodes.map((node) => [node.id, node.layer]));
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const e of edges) {
    const sourceLayer = nodeLayer.get(e.source);
    const targetLayer = nodeLayer.get(e.target);
    if (
      sourceLayer !== undefined &&
      targetLayer !== undefined &&
      sourceLayer < targetLayer
    ) {
      (
        incoming.get(e.target) ??
        incoming.set(e.target, []).get(e.target)!
      ).push(e.source);
      (
        outgoing.get(e.source) ??
        outgoing.set(e.source, []).get(e.source)!
      ).push(e.target);
    }
  }

  if (optimizeNodeOrder) {
    const hierarchyLayers = new Set(
      layerIndexes.filter((layer) => {
        const securableRanks = new Set(
          cols
            .get(layer)!
            .map((node) => rank(node))
            .filter((value) => value < 99),
        );
        return securableRanks.size > 1;
      }),
    );

    const orderLayer = (layer: number, neighbors: Map<string, string[]>) => {
      let col = cols.get(layer)!;
      if (hierarchyLayers.has(layer)) return;
      const currentOrder = new Map(col.map((node, index) => [node.id, index]));
      const desiredById = new Map(
        col.map((n) => {
          const nbrs = neighbors.get(n.id) ?? [];
          if (!nbrs.length) return [n.id, slot.get(n.id)!] as const;
          const avg =
            nbrs.reduce((sum, neighbor) => sum + (slot.get(neighbor) ?? 0), 0) /
            nbrs.length;
          return [n.id, avg] as const;
        }),
      );
      col = [...col].sort(
        (a, b) =>
          desiredById.get(a.id)! - desiredById.get(b.id)! ||
          rank(a) - rank(b) ||
          currentOrder.get(a.id)! - currentOrder.get(b.id)!,
      );
      cols.set(layer, col);

      const desired = col.map((node) => desiredById.get(node.id)!);
      const separated = desired.every(
        (value, index) => index === 0 || value - desired[index - 1] >= 1,
      );
      if (separated) {
        col.forEach((node, index) => slot.set(node.id, desired[index]));
      } else {
        const base = (maxRows - col.length) / 2;
        col.forEach((node, index) => slot.set(node.id, base + index));
      }
    };

    for (const layer of [...layerIndexes].reverse()) {
      orderLayer(layer, outgoing);
    }
    for (const layer of layerIndexes) {
      orderLayer(layer, incoming);
    }
  }

  // Widen a column gap only when an edge label leaving that column would not
  // fit between the nodes; short-label graphs keep the compact gap.
  const labelGap = new Map<number, number>();
  for (const e of edges) {
    const sourceLayer = nodeLayer.get(e.source);
    if (sourceLayer === undefined || e.kind === "contains" || !e.label) continue;
    const chipW = e.label.length * EDGE_LABEL_CHAR_W + 8;
    labelGap.set(
      sourceLayer,
      Math.max(labelGap.get(sourceLayer) ?? 0, chipW + 12),
    );
  }
  const colWidth = (layer: number, cap: number) =>
    Math.max(
      ...cols.get(layer)!.map((node) => Math.min(cap, naturalWidths.get(node.id)!)),
    );
  const gapAfter = (layer: number, gap: number) =>
    Math.max(gap, labelGap.get(layer) ?? 0);
  const lastLayer = layerIndexes[layerIndexes.length - 1];
  const lastLayerBulge = edges.some(
    (e) =>
      nodeLayer.get(e.source) === lastLayer &&
      nodeLayer.get(e.target) === lastLayer,
  )
    ? SAME_LAYER_EDGE_BULGE + 2
    : 0;
  const totalWidth = (cap: number, gap: number) =>
    LEFT_PAD +
    Math.max(RIGHT_PAD, lastLayerBulge) +
    layerIndexes.reduce(
      (sum, layer, i) =>
        sum +
        colWidth(layer, cap) +
        (i < layerIndexes.length - 1 ? gapAfter(layer, gap) : 0),
      0,
    );
  const steps = [
    { cap: nodeWidthCap, gap: COL_GAP },
    ...FIT_STEPS.filter((step) => step.cap < nodeWidthCap),
  ];
  const fit =
    maxWidth === undefined
      ? steps[0]
      : (steps.find((step) => totalWidth(step.cap, step.gap) <= maxWidth) ??
        steps[steps.length - 1]);

  const allSlots = Array.from(slot.values());
  const minSlot = Math.min(...allSlots);
  const pos = new Map<string, Positioned>();
  let x = LEFT_PAD;
  for (const layer of layerIndexes) {
    for (const n of cols.get(layer)!) {
      pos.set(n.id, {
        ...n,
        x,
        y: TOP_PAD + (slot.get(n.id)! - minSlot) * ROW_PITCH,
        width: Math.min(fit.cap, naturalWidths.get(n.id)!),
      });
    }
    x += colWidth(layer, fit.cap) + gapAfter(layer, fit.gap);
  }
  return pos;
}

export function ChainGraphView({
  graph,
  ariaLabel,
  hideEdgeKinds = [],
  showLegend = true,
  expandableNodeIds,
  expandedNodeIds,
  onNodeToggle,
  activatableNodeIds,
  onNodeActivate,
  onNodeEffectActivate,
  getNodeActivationLabel,
  activationRole = "link",
  selectedNodeId,
  highlightedNodeIds,
  highlightedEdgeKeys,
  onCanvasActivate,
  optimizeNodeOrder = false,
}: {
  graph: ChainGraphOut;
  ariaLabel: string;
  hideEdgeKinds?: string[];
  showLegend?: boolean;
  expandableNodeIds?: ReadonlySet<string>;
  expandedNodeIds?: ReadonlySet<string>;
  onNodeToggle?: (nodeId: string) => void;
  activatableNodeIds?: ReadonlySet<string>;
  onNodeActivate?: (nodeId: string) => void;
  onNodeEffectActivate?: (nodeId: string, effect: "filter" | "mask") => void;
  getNodeActivationLabel?: (node: ChainGraphNodeOut) => string;
  activationRole?: "button" | "link";
  selectedNodeId?: string;
  highlightedNodeIds?: ReadonlySet<string>;
  highlightedEdgeKeys?: ReadonlySet<string>;
  onCanvasActivate?: () => void;
  optimizeNodeOrder?: boolean;
}) {
  const { skin } = useSkin();
  const resourceId = useId().replaceAll(":", "");
  const arrowId = `chain-arrow-${resourceId}`;
  const containsArrowId = `chain-contains-arrow-${resourceId}`;
  const shadowId = `dbx-shadow-${resourceId}`;
  const dbx = skin === "databricks";
  const hidden = new Set(hideEdgeKinds);
  const edges = graph.edges.filter((e) => !hidden.has(e.kind));
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState<number>();
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const updateWidth = () => setContainerWidth(container.clientWidth);
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);
  const nodeWidthCap =
    containerWidth !== undefined && containerWidth < 1100
      ? NARROW_NODE_MAX_W
      : NODE_MAX_W;
  // drop nodes that become orphaned once edges are hidden (except the user root)
  const connected = new Set<string>();
  edges.forEach((e) => {
    connected.add(e.source);
    connected.add(e.target);
  });
  const nodes = graph.nodes.filter(
    (n) => connected.has(n.id) || n.kind === "user",
  );
  const pos = useMemo(
    () =>
      layoutLayers(
        nodes,
        edges,
        nodeWidthCap,
        optimizeNodeOrder,
        containerWidth === undefined ? undefined : containerWidth / GRAPH_SCALE,
      ),
    [graph, hideEdgeKinds.join(","), nodeWidthCap, optimizeNodeOrder, containerWidth],
  );
  // Same-layer edges bulge out to the right of their nodes; keep them in view.
  const bulgeRight = edges.map((e) => {
    const a = pos.get(e.source);
    const b = pos.get(e.target);
    if (!a || !b || a.layer !== b.layer) return 0;
    const bulge =
      e.kind === "contains" ? SAME_LAYER_CONTAINS_BULGE : SAME_LAYER_EDGE_BULGE;
    return Math.max(a.x + a.width, b.x + b.width) + bulge + 2;
  });
  const width =
    Math.max(
      ...Array.from(pos.values()).map((node) => node.x + node.width + RIGHT_PAD),
      ...bulgeRight,
      120,
    );
  const height =
    Math.max(...Array.from(pos.values()).map((p) => p.y + NODE_H), 120) + 28;

  const legendKinds = Array.from(new Set(nodes.map((n) => n.kind)));
  const [hovered, setHovered] = useState<Positioned | null>(null);
  const hasHighlightedPath = (highlightedEdgeKeys?.size ?? 0) > 0;
  const renderedScale = GRAPH_SCALE;

  return (
    <div
      ref={containerRef}
      data-graph-canvas
      className="overflow-hidden rounded-md border relative"
      style={dbx ? { backgroundColor: "var(--dbx-canvas)" } : undefined}
      onClick={(event) => {
        const target = event.target as Element;
        if (!target.closest("[data-graph-node]")) onCanvasActivate?.();
      }}
    >
      <div ref={scrollRef} className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width * GRAPH_SCALE}
        height={height * GRAPH_SCALE}
        preserveAspectRatio="xMinYMin meet"
        className="block max-w-none"
        role={onNodeToggle || onNodeActivate ? "group" : "img"}
        aria-label={ariaLabel}
      >
        <defs>
          <marker
            id={arrowId}
            viewBox="0 0 10 10"
            refX={9}
            refY={5}
            markerWidth={7}
            markerHeight={7}
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" />
          </marker>
          <marker
            id={containsArrowId}
            viewBox="0 0 10 10"
            refX={9}
            refY={5}
            markerWidth={6}
            markerHeight={6}
            markerUnits="userSpaceOnUse"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" />
          </marker>
          {dbx && (
            <filter id={shadowId} x="-20%" y="-20%" width="140%" height="160%">
              <feDropShadow
                dx="0"
                dy="1"
                stdDeviation="2.5"
                floodColor="var(--dbx-shadow)"
                floodOpacity="0.16"
              />
            </filter>
          )}
        </defs>
        {(() => {
          const perSource = new Map<string, number>();
          // Edges converging on one node land their labels in the same spot;
          // draw each distinct label once per target so they don't pile up,
          // preferring a highlighted edge so its label stays visible.
          const labelOwner = new Map<string, number>();
          edges.forEach((e, i) => {
            const key = `${e.target}\u0000${e.label}`;
            const owner = labelOwner.get(key);
            if (
              owner === undefined ||
              (!highlightedEdgeKeys?.has(chainEdgeKey(edges[owner])) &&
                highlightedEdgeKeys?.has(chainEdgeKey(e)))
            ) {
              labelOwner.set(key, i);
            }
          });
          return edges.map((e, i) => {
            const a = pos.get(e.source);
            const b = pos.get(e.target);
            if (!a || !b) return null;
            const baseStyle = EDGE_STYLE[e.kind] ?? { stroke: "currentColor" };
            // UC data-lineage style: one uniform blue edge color; dash pattern
            // still distinguishes cascade/inherit/tagged so meaning survives.
            const style =
              dbx && !MEANINGFUL_EDGE_KINDS.has(e.kind)
                ? { ...baseStyle, stroke: "var(--dbx-edge)" }
                : baseStyle;
            const highlighted = highlightedEdgeKeys?.has(chainEdgeKey(e)) ?? false;
            const sameLayer = a.layer === b.layer;
            let routedAroundNode = false;
            let d: string;
            let lx = 0;
            let ly = 0;
            if (sameLayer) {
              const bulge =
                e.kind === "contains"
                  ? SAME_LAYER_CONTAINS_BULGE
                  : SAME_LAYER_EDGE_BULGE;
              const x1 = a.x + a.width;
              const x2 = b.x + b.width;
              const routeX = Math.max(x1, x2) + bulge;
              d = `M ${x1} ${a.y + NODE_H / 2} C ${routeX} ${a.y + NODE_H / 2}, ${routeX} ${b.y + NODE_H / 2}, ${x2} ${b.y + NODE_H / 2}`;
              lx = routeX - 6;
              ly = (a.y + b.y) / 2 + NODE_H / 2;
            } else {
              const x1 = a.x + a.width;
              const y1 = a.y + NODE_H / 2;
              const x2 = b.x;
              const y2 = b.y + NODE_H / 2;
              const mx = (x1 + x2) / 2;
              const intermediateNodes = Array.from(pos.values()).filter(
                (node) =>
                  node.id !== a.id &&
                  node.id !== b.id &&
                  node.x > a.x &&
                  node.x < b.x,
              );
              const blocked = intermediateNodes.some((node) => {
                const nodeCenterX = node.x + node.width / 2;
                const progress = (nodeCenterX - x1) / (x2 - x1);
                const lineY = y1 + (y2 - y1) * progress;
                return lineY >= node.y - 10 && lineY <= node.y + NODE_H + 10;
              });
              if (blocked) {
                const above = Math.max(
                  16,
                  Math.min(...intermediateNodes.map((node) => node.y)) - 24,
                );
                const below =
                  Math.max(
                    ...intermediateNodes.map((node) => node.y + NODE_H),
                  ) + 24;
                const aboveCost = Math.abs(y1 - above) + Math.abs(y2 - above);
                const belowCost = Math.abs(y1 - below) + Math.abs(y2 - below);
                const channelY = aboveCost <= belowCost ? above : below;
                const lead = Math.min(56, (x2 - x1) / 4);
                d = `M ${x1} ${y1} C ${x1 + lead / 2} ${y1}, ${x1 + lead / 2} ${channelY}, ${x1 + lead} ${channelY} L ${x2 - lead} ${channelY} C ${x2 - lead / 2} ${channelY}, ${x2 - lead / 2} ${y2}, ${x2} ${y2}`;
                lx = (x1 + x2) / 2;
                ly = Math.max(14, channelY - 7);
                routedAroundNode = true;
              } else {
                d = `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
              }
              if (e.kind === "grant" || e.kind === "effect") {
                const occ = perSource.get(e.source) ?? 0;
                perSource.set(e.source, occ + 1);
                lx = x1 + Math.min(62, (x2 - x1) / 2);
                ly = y1 - 8 - occ * 15;
              } else if (!routedAroundNode) {
                // Straight edges label at the midpoint so the chip fits the
                // column gap; fan-outs label near the target to disambiguate.
                const t = Math.abs(y2 - y1) < 1 ? 0.5 : 0.72;
                const omt = 1 - t;
                lx =
                  omt ** 3 * x1 +
                  3 * omt ** 2 * t * mx +
                  3 * omt * t ** 2 * mx +
                  t ** 3 * x2;
                ly =
                  (omt ** 3 + 3 * omt ** 2 * t) * y1 +
                  (3 * omt * t ** 2 + t ** 3) * y2 -
                  6 -
                  (i % 3) * 11;
              }
              ly = Math.max(14, ly);
            }
            const showLabel =
              e.kind !== "contains" &&
              labelOwner.get(`${e.target}\u0000${e.label}`) === i;
            return (
              <g
                key={i}
                data-edge-highlighted={hasHighlightedPath ? highlighted : undefined}
                opacity={hasHighlightedPath && !highlighted ? 0.16 : 1}
              >
                <path
                  d={d}
                  data-edge-kind={e.kind}
                  data-edge-source={e.source}
                  data-edge-target={e.target}
                  data-edge-label={e.label}
                  data-edge-routed-around-node={routedAroundNode || undefined}
                  fill="none"
                  stroke={style.stroke}
                  strokeDasharray={style.dash}
                  strokeWidth={highlighted ? 2.75 : 1.5}
                  opacity={e.kind === "contains" ? 0.45 : 0.9}
                  className={e.kind === "contains" ? "text-muted-foreground" : ""}
                  markerEnd={
                    style.arrow
                      ? `url(#${e.kind === "contains" ? containsArrowId : arrowId})`
                      : undefined
                  }
                />
                {showLabel && (
                  (() => {
                    const chipW = e.label.length * EDGE_LABEL_CHAR_W + 8;
                    const chipX =
                      sameLayer ? lx - chipW + 4 : lx - chipW / 2;
                    return (
                      <>
                        {/* white chip so labels stay legible over edges/grid */}
                        <rect
                          x={chipX}
                          y={ly - 10}
                          width={chipW}
                          height={14}
                          rx={3}
                          fill={dbx ? "var(--dbx-label-bg)" : "var(--background)"}
                          opacity={0.9}
                          className="pointer-events-none"
                        />
                        <text
                          x={lx}
                          y={ly}
                          textAnchor={sameLayer ? "end" : "middle"}
                          fontSize={EDGE_LABEL_FONT}
                          fontFamily="monospace"
                          fill={dbx ? "var(--dbx-muted)" : undefined}
                          className={dbx ? "pointer-events-none" : "fill-muted-foreground pointer-events-none"}
                        >
                          {e.label}
                        </text>
                      </>
                    );
                  })()
                )}
              </g>
            );
          });
        })()}
        {Array.from(pos.values()).map((n) => {
          const color = KIND_COLOR[n.kind] ?? "#888";
          const textX = n.x + 8;
          const isHot = hovered?.id === n.id;
          const canExpand = expandableNodeIds?.has(n.id) ?? false;
          const isExpanded = expandedNodeIds?.has(n.id) ?? false;
          const interactive = canExpand && onNodeToggle !== undefined;
          const activatable =
            (activatableNodeIds?.has(n.id) ?? false) &&
            onNodeActivate !== undefined;
          const isSelected = selectedNodeId === n.id;
          const isHighlighted = highlightedNodeIds?.has(n.id) ?? false;
          const clickable = interactive || activatable;
          const hasFilterEffect = n.row_filtered || n.row_filter_targeted;
          const hasMaskEffect = n.masked || n.mask_targeted;
          const effectIconCount = Number(hasFilterEffect) + Number(hasMaskEffect);
          const maxLabelLength = Math.max(
            12,
            Math.floor(n.width / (LABEL_CHAR_W + 0.1)) -
              (interactive ? 4 : 1) -
              effectIconCount * 4,
          );
          const inner = (
            <>
              {/* highlight halo behind the hovered node */}
              {isHot && (
                <rect
                  x={n.x - 3}
                  y={n.y - 3}
                  width={n.width + 6}
                  height={NODE_H + 6}
                  rx={dbx ? 10 : 7}
                  fill="none"
                  stroke={color}
                  strokeWidth={1}
                  opacity={0.4}
                  className="pointer-events-none"
                />
              )}
              <rect
                x={n.x}
                y={n.y}
                width={n.width}
                height={NODE_H}
                rx={dbx ? 8 : 5}
                fill={dbx ? "var(--dbx-node)" : "var(--background)"}
                stroke={color}
                strokeWidth={isSelected ? 2 : isHot ? 1.5 : 1.25}
                filter={dbx ? `url(#${shadowId})` : undefined}
                className={n.github_url || clickable ? "cursor-pointer" : undefined}
              />
              {dbx && (
                <>
                  {/* connection ports on left/right edges */}
                  <circle cx={n.x} cy={n.y + NODE_H / 2} r={3}
                    fill="var(--dbx-port)" stroke="var(--dbx-port-border)" strokeWidth={1}
                    className="pointer-events-none" />
                  <circle cx={n.x + n.width} cy={n.y + NODE_H / 2} r={3}
                    fill="var(--dbx-port)" stroke="var(--dbx-port-border)" strokeWidth={1}
                    className="pointer-events-none" />
                </>
              )}
              <text
                x={textX}
                y={n.y + (n.sublabel ? 20 : 29)}
                fontSize={LABEL_FONT}
                fontFamily="monospace"
                fill={dbx ? "var(--dbx-text)" : undefined}
                className={dbx ? "pointer-events-none" : "fill-foreground pointer-events-none"}
                fontWeight={dbx ? 600 : 400}
              >
                {n.label.length > maxLabelLength
                  ? `…${n.label.slice(-(maxLabelLength - 1))}`
                  : n.label}
              </text>
              {n.sublabel && (
                <text
                  x={textX}
                  y={n.y + 37}
                  fontSize={SUBLABEL_FONT}
                  fill={dbx ? "var(--dbx-muted)" : undefined}
                  className={dbx ? "pointer-events-none" : "fill-muted-foreground pointer-events-none"}
                  style={{ textTransform: "uppercase", letterSpacing: "0.06em" }}
                >
                  {n.sublabel}
                </text>
              )}
              {hasFilterEffect && (
                <g
                  data-node-effect="filtered"
                  data-effect-applied={n.row_filtered || undefined}
                  className={
                    onNodeEffectActivate
                      ? "cursor-pointer"
                      : "pointer-events-none"
                  }
                  role={onNodeEffectActivate ? "button" : undefined}
                  tabIndex={onNodeEffectActivate ? 0 : undefined}
                  aria-label={
                    onNodeEffectActivate
                      ? `${n.row_filtered ? "Show" : "Show exempt"} row filter Why for ${n.id}`
                      : undefined
                  }
                  onClick={(event) => {
                    if (!onNodeEffectActivate) return;
                    event.stopPropagation();
                    onNodeEffectActivate(n.id, "filter");
                  }}
                  onKeyDown={(event) => {
                    if (
                      onNodeEffectActivate &&
                      (event.key === "Enter" || event.key === " ")
                    ) {
                      event.preventDefault();
                      event.stopPropagation();
                      onNodeEffectActivate(n.id, "filter");
                    }
                  }}
                >
                  <title>
                    {n.row_filtered
                      ? "Rows filtered"
                      : "Row filter policy (not applied)"}
                  </title>
                  <rect
                    data-effect-badge
                    x={n.x + n.width - (hasMaskEffect ? 56 : 28)}
                    y={n.y + BADGE_Y}
                    width={BADGE_SIZE}
                    height={BADGE_SIZE}
                    rx={7}
                    fill={
                      n.row_filtered
                        ? "var(--effect-filter-background)"
                        : "var(--muted)"
                    }
                    stroke={
                      n.row_filtered
                        ? "var(--effect-filter-border)"
                        : "var(--border)"
                    }
                  />
                  <ListFilter
                    data-effect-icon
                    x={n.x + n.width - (hasMaskEffect ? 50 : 22)}
                    y={n.y + BADGE_Y + 6}
                    width={12}
                    height={12}
                    strokeWidth={2}
                    color={
                      n.row_filtered
                        ? "var(--effect-filter-foreground)"
                        : "var(--muted-foreground)"
                    }
                  />
                </g>
              )}
              {hasMaskEffect && (
                <g
                  data-node-effect="masked"
                  data-effect-applied={n.masked || undefined}
                  className={
                    onNodeEffectActivate
                      ? "cursor-pointer"
                      : "pointer-events-none"
                  }
                  role={onNodeEffectActivate ? "button" : undefined}
                  tabIndex={onNodeEffectActivate ? 0 : undefined}
                  aria-label={
                    onNodeEffectActivate
                      ? `${n.masked ? "Show" : "Show exempt"} mask Why for ${n.id}`
                      : undefined
                  }
                  onClick={(event) => {
                    if (!onNodeEffectActivate) return;
                    event.stopPropagation();
                    onNodeEffectActivate(n.id, "mask");
                  }}
                  onKeyDown={(event) => {
                    if (
                      onNodeEffectActivate &&
                      (event.key === "Enter" || event.key === " ")
                    ) {
                      event.preventDefault();
                      event.stopPropagation();
                      onNodeEffectActivate(n.id, "mask");
                    }
                  }}
                >
                  <title>
                    {n.masked
                      ? n.kind === "column"
                        ? "Masked column"
                        : "Masked columns"
                      : "Mask policy (not applied)"}
                  </title>
                  <rect
                    data-effect-badge
                    x={n.x + n.width - 28}
                    y={n.y + BADGE_Y}
                    width={BADGE_SIZE}
                    height={BADGE_SIZE}
                    rx={7}
                    fill={
                      n.masked ? "var(--effect-mask-background)" : "var(--muted)"
                    }
                    stroke={
                      n.masked ? "var(--effect-mask-border)" : "var(--border)"
                    }
                  />
                  <EyeOff
                    data-effect-icon
                    x={n.x + n.width - 22}
                    y={n.y + BADGE_Y + 6}
                    width={12}
                    height={12}
                    strokeWidth={2}
                    color={
                      n.masked
                        ? "var(--effect-mask-foreground)"
                        : "var(--muted-foreground)"
                    }
                  />
                </g>
              )}
              {interactive && (
                <text
                  x={n.x + n.width - 14}
                  y={n.y + NODE_H / 2 + 5}
                  textAnchor="middle"
                  fontSize={16}
                  fontWeight={600}
                  fill={dbx ? "var(--dbx-muted)" : undefined}
                  className={dbx ? "pointer-events-none" : "fill-muted-foreground pointer-events-none"}
                >
                  {isExpanded ? "−" : "+"}
                </text>
              )}
            </>
          );
          return n.github_url && !activatable ? (
            <a
              key={n.id}
              data-graph-node
              data-node-id={n.id}
              data-node-label={n.label}
              data-node-filtered={n.row_filtered || undefined}
              data-node-filter-targeted={n.row_filter_targeted || undefined}
              data-node-masked={n.masked || undefined}
              data-node-mask-targeted={n.mask_targeted || undefined}
              data-path-highlighted={hasHighlightedPath ? isHighlighted : undefined}
              href={n.github_url}
              target="_blank"
              rel="noopener noreferrer"
              onMouseEnter={() => setHovered(n)}
              onMouseLeave={() => setHovered((h) => (h?.id === n.id ? null : h))}
              onFocus={() => setHovered(n)}
              onBlur={() => setHovered((h) => (h?.id === n.id ? null : h))}
              style={{ opacity: hasHighlightedPath && !isHighlighted ? 0.32 : 1 }}
            >
              {inner}
            </a>
          ) : (
            <g
              key={n.id}
              data-graph-node
              data-node-id={n.id}
              data-node-label={n.label}
              data-node-filtered={n.row_filtered || undefined}
              data-node-filter-targeted={n.row_filter_targeted || undefined}
              data-node-masked={n.masked || undefined}
              data-node-mask-targeted={n.mask_targeted || undefined}
              data-path-highlighted={hasHighlightedPath ? isHighlighted : undefined}
              tabIndex={clickable || n.source ? 0 : undefined}
              role={
                activatable
                  ? activationRole
                  : interactive
                    ? "button"
                    : n.source
                      ? "group"
                      : undefined
              }
              aria-label={
                activatable
                  ? getNodeActivationLabel?.(n) ??
                    `Open table access details for ${n.label}`
                  : interactive
                  ? `${isExpanded ? "Collapse" : "Expand"} ${n.label}`
                  : n.source
                    ? `${n.label}, source ${n.source}`
                    : undefined
              }
              onClick={() => {
                if (activatable) onNodeActivate?.(n.id);
                else if (interactive) onNodeToggle?.(n.id);
              }}
              onKeyDown={(event) => {
                if (
                  clickable &&
                  (event.key === "Enter" || event.key === " ")
                ) {
                  event.preventDefault();
                  if (activatable) onNodeActivate?.(n.id);
                  else onNodeToggle?.(n.id);
                }
              }}
              onMouseEnter={() => setHovered(n)}
              onMouseLeave={() => setHovered((h) => (h?.id === n.id ? null : h))}
              onFocus={() => setHovered(n)}
              onBlur={() => setHovered((h) => (h?.id === n.id ? null : h))}
              aria-current={isSelected ? "true" : undefined}
              opacity={hasHighlightedPath && !isHighlighted ? 0.32 : 1}
            >
              {inner}
            </g>
          );
        })}
      </svg>
      </div>
      {/* Portal the fast HTML tooltip above every graph/card stacking context. */}
      {hovered &&
        containerRef.current &&
        (hovered.source ||
          hovered.github_url ||
          activatableNodeIds?.has(hovered.id) ||
          hovered.label.length > 24) &&
        createPortal(
          <div
            role="tooltip"
            data-graph-tooltip
            className="pointer-events-none fixed z-[100] rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md"
            style={{
              left: Math.max(
                8,
                Math.min(
                  containerRef.current.getBoundingClientRect().left +
                    hovered.x * renderedScale -
                    (scrollRef.current?.scrollLeft ?? 0),
                  window.innerWidth - 268,
                ),
              ),
              top: Math.max(
                8,
                Math.min(
                  containerRef.current.getBoundingClientRect().top +
                    (hovered.y + NODE_H + 8) * renderedScale,
                  window.innerHeight - 120,
                ),
              ),
              maxWidth: 260,
            }}
          >
            <div className="break-all font-mono font-medium text-foreground">
              {hovered.id}
            </div>
            {hovered.source && (
              <div className="break-all font-mono text-[11px] text-muted-foreground">
                ↳ {hovered.source}
              </div>
            )}
          </div>,
          document.body,
        )}
      {showLegend && (
        <div className="flex gap-4 px-3 py-2 border-t text-xs text-muted-foreground flex-wrap">
          {legendKinds.map((kind) => (
            <span key={kind} className="inline-flex items-center gap-1">
              <span
                className="inline-block size-2 rounded-full"
                style={{ background: KIND_COLOR[kind] }}
              />
              {KIND_LABEL[kind] ?? kind}
            </span>
          ))}
          {edges.some((e) => e.kind === "drift") && (
            <span className="inline-flex items-center gap-1">
              <span
                className="inline-block w-4 border-t-2 border-dashed"
                style={{ borderColor: "var(--graph-drift)" }}
              />
              drift: declared, not held
            </span>
          )}
          {!hidden.has("cascade") && (
            <span className="inline-flex items-center gap-1">
              <span
                className="inline-block w-4 border-t-2 border-dashed"
                style={{ borderColor: "var(--graph-securable)" }}
              />
              ▶ cascade / inherit
            </span>
          )}
          {!hidden.has("tagged") && (
            <span className="inline-flex items-center gap-1">
              <span
                className="inline-block w-4 border-t-2 border-dashed"
                style={{ borderColor: "var(--graph-tag)" }}
              />
              tagged on
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export function ChainGraph({
  principal,
  table,
  hideColumnMasks = false,
  hideRowFilters = false,
  hideGrants = false,
  hideUpstreamCascade = false,
  focusColumn,
  selectedNodeId,
  onNodeActivate,
  hideDirectColumnEdges = false,
  onGraphChange,
}: {
  principal: string;
  table: string;
  hideColumnMasks?: boolean;
  hideRowFilters?: boolean;
  hideGrants?: boolean;
  hideUpstreamCascade?: boolean;
  focusColumn?: string;
  selectedNodeId?: string;
  onNodeActivate?: (node: ChainGraphNodeOut) => void;
  hideDirectColumnEdges?: boolean;
  onGraphChange?: (graph: ChainGraphOut) => void;
}) {
  // The backend omits the whole column-mask branch (policy + pii tags +
  // columns) when include_column_masks is false, keeping row filters — so the
  // table view stays about table access without dangling nodes.
  const { data } = useExplainGraphSuspense({
    params: {
      principal,
      table,
      include_column_masks: !hideColumnMasks,
      include_row_filters: !hideRowFilters,
      include_grants: !hideGrants,
      focus_column: focusColumn,
    },
  });
  const graph = data.data;
  useEffect(() => onGraphChange?.(graph), [graph, onGraphChange]);
  const activatableNodeIds = onNodeActivate
    ? new Set(graph.nodes.map((node) => node.id))
    : undefined;
  return (
    <ChainGraphView
      graph={graph}
      ariaLabel={`Why chain from ${principal} to ${table}`}
      hideEdgeKinds={[
        ...(hideUpstreamCascade ? ["cascade"] : []),
        ...(hideDirectColumnEdges ? ["argument", "effect"] : []),
      ]}
      activatableNodeIds={activatableNodeIds}
      onNodeActivate={(nodeId) => {
        const node = graph.nodes.find((candidate) => candidate.id === nodeId);
        if (node) onNodeActivate?.(node);
      }}
      getNodeActivationLabel={(node) => `Inspect ${node.sublabel ?? node.kind} ${node.label}`}
      activationRole="button"
      selectedNodeId={selectedNodeId}
      optimizeNodeOrder
    />
  );
}

export function ChainGraphStepsView({
  graph,
  hideEdgeKinds = [],
  activatableNodeIds,
  onNodeActivate,
  selectedNodeId,
}: {
  graph: ChainGraphOut;
  hideEdgeKinds?: string[];
  activatableNodeIds?: ReadonlySet<string>;
  onNodeActivate?: (nodeId: string) => void;
  selectedNodeId?: string;
}) {
  const hidden = new Set(hideEdgeKinds);
  const edges = graph.edges.filter((edge) => !hidden.has(edge.kind));
  const connected = new Set<string>();
  edges.forEach((edge) => {
    connected.add(edge.source);
    connected.add(edge.target);
  });
  const nodes = graph.nodes.filter(
    (node) => connected.has(node.id) || node.kind === "user",
  ).sort(
    (a, b) => a.layer - b.layer || a.id.localeCompare(b.id),
  );
  const incoming = new Map<string, string[]>();
  for (const edge of edges) {
    const labels = incoming.get(edge.target) ?? [];
    labels.push(edge.label);
    incoming.set(edge.target, labels);
  }
  return (
    <ol className="space-y-2 rounded-md border p-3">
      {nodes.map((node, index) => {
        const transitions = incoming.get(node.id) ?? [];
        const kind = node.sublabel || node.kind;
        return (
          <li key={node.id}>
            <button
              type="button"
              disabled={!activatableNodeIds?.has(node.id)}
              onClick={() => onNodeActivate?.(node.id)}
              className={`flex w-full gap-3 rounded-md p-1.5 text-left text-sm disabled:opacity-100 ${
                selectedNodeId === node.id
                  ? "bg-muted"
                  : activatableNodeIds?.has(node.id)
                    ? "hover:bg-muted/60"
                    : ""
              }`}
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
                {index + 1}
              </span>
              <span>
                {transitions.length > 0 && (
                  <span className="font-mono text-xs text-muted-foreground">
                    {transitions.join(" / ")} →{" "}
                  </span>
                )}
                <span className="font-medium">{node.label}</span>
                <span className="ml-1.5 text-xs text-muted-foreground">
                  ({kind})
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function ChainGraphSteps({
  principal,
  table,
  hideColumnMasks = false,
  hideRowFilters = false,
  hideGrants = false,
  hideUpstreamCascade = false,
  focusColumn,
  hideDirectColumnEdges = false,
  onGraphChange,
}: {
  principal: string;
  table: string;
  hideColumnMasks?: boolean;
  hideRowFilters?: boolean;
  hideGrants?: boolean;
  hideUpstreamCascade?: boolean;
  focusColumn?: string;
  hideDirectColumnEdges?: boolean;
  onGraphChange?: (graph: ChainGraphOut) => void;
}) {
  const { data } = useExplainGraphSuspense({
    params: {
      principal,
      table,
      include_column_masks: !hideColumnMasks,
      include_row_filters: !hideRowFilters,
      include_grants: !hideGrants,
      focus_column: focusColumn,
    },
  });
  const graph = data.data;
  useEffect(() => onGraphChange?.(graph), [graph, onGraphChange]);
  return (
    <ChainGraphStepsView
      graph={graph}
      hideEdgeKinds={[
        ...(hideUpstreamCascade ? ["cascade"] : []),
        ...(hideDirectColumnEdges ? ["argument", "effect"] : []),
      ]}
    />
  );
}

export function ColumnChainGraph({
  principal,
  column,
  hideDirectColumnEdges = false,
  selectedNodeId,
  onNodeActivate,
  onGraphChange,
}: {
  principal: string;
  column: string;
  hideDirectColumnEdges?: boolean;
  selectedNodeId?: string;
  onNodeActivate?: (node: ChainGraphNodeOut) => void;
  onGraphChange?: (graph: ChainGraphOut) => void;
}) {
  const { data } = useExplainColumnGraphSuspense({ params: { principal, column } });
  const graph = data.data;
  useEffect(() => onGraphChange?.(graph), [graph, onGraphChange]);
  const activatableNodeIds = onNodeActivate
    ? new Set(graph.nodes.map((node) => node.id))
    : undefined;
  return (
    <ChainGraphView
      graph={graph}
      ariaLabel={`Why chain from ${principal} to ${column}`}
      hideEdgeKinds={hideDirectColumnEdges ? ["argument", "effect"] : []}
      activatableNodeIds={activatableNodeIds}
      onNodeActivate={(nodeId) => {
        const node = graph.nodes.find((candidate) => candidate.id === nodeId);
        if (node) onNodeActivate?.(node);
      }}
      getNodeActivationLabel={(node) => `Inspect ${node.sublabel ?? node.kind} ${node.label}`}
      activationRole="button"
      selectedNodeId={selectedNodeId}
      optimizeNodeOrder
    />
  );
}
