import type { GraphEdgeOut, GraphOut, InverseGraphOut } from "@/lib/api";

export const UNIFIED_NODE_KINDS = [
  "user",
  "group",
  "policy",
  "manual",
  "tag",
  "catalog",
  "schema",
  "table",
  "column",
] as const;

export function withSelectedColumn<T extends GraphOut>(
  graph: T,
  column?: string,
  effects?: {
    mask_targeted?: boolean;
    masked?: boolean;
    row_filter_targeted?: boolean;
    row_filtered?: boolean;
  },
): T {
  if (!column || column.split(".").length !== 4) return graph;
  const table = column.split(".").slice(0, 3).join(".");
  if (
    graph.nodes.some((node) => node.id === column) ||
    !graph.nodes.some((node) => node.id === table && node.kind === "table")
  ) {
    return graph;
  }
  return {
    ...graph,
    nodes: [
      ...graph.nodes,
      {
        id: column,
        kind: "column",
        label: column.split(".").at(-1)!,
        ...effects,
      },
    ],
    edges: [
      ...graph.edges,
      {
        source: table,
        target: column,
        kind: "contains",
        label: "column",
      },
    ],
  };
}

export function hideMaskedPrincipals<T extends InverseGraphOut>(
  graph: T,
  hideMasked: boolean,
): T {
  if (!hideMasked || graph.target_type !== "column") return graph;
  const visibleEffects = graph.principal_effects.filter(
    (effect) => effect.principal_kind === "group" || !effect.masked,
  );
  const hiddenPrincipals = new Set(
    graph.principal_effects
      .filter((effect) => effect.principal_kind !== "group" && effect.masked)
      .map((effect) => effect.principal),
  );
  const outgoing = new Map<string, GraphEdgeOut[]>();
  for (const edge of graph.edges) {
    const edges = outgoing.get(edge.source) ?? [];
    edges.push(edge);
    outgoing.set(edge.source, edges);
  }
  const visibleNodes = new Set(visibleEffects.map((effect) => effect.principal));
  const queue = [...visibleNodes];
  while (queue.length > 0) {
    const source = queue.shift()!;
    for (const edge of outgoing.get(source) ?? []) {
      if (visibleNodes.has(edge.target)) continue;
      visibleNodes.add(edge.target);
      queue.push(edge.target);
    }
  }
  return {
    ...graph,
    principal_effects: visibleEffects,
    nodes: graph.nodes
      .filter((node) => visibleNodes.has(node.id))
      .map((node) =>
        hiddenPrincipals.has(node.id)
          ? {
              ...node,
              effect_principal: false,
              masked: false,
              mask_targeted: false,
              row_filtered: false,
              row_filter_targeted: false,
            }
          : node,
      ),
    edges: graph.edges.filter(
      (edge) => visibleNodes.has(edge.source) && visibleNodes.has(edge.target),
    ),
  };
}

export function focusUnifiedGraph(
  graph: GraphOut,
  query: string,
  focusedKinds: ReadonlySet<string>,
): GraphOut {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized && focusedKinds.size === UNIFIED_NODE_KINDS.length) {
    return graph;
  }

  const incoming = new Map<string, GraphEdgeOut[]>();
  const outgoing = new Map<string, GraphEdgeOut[]>();
  for (const edge of graph.edges) {
    const inEdges = incoming.get(edge.target) ?? [];
    inEdges.push(edge);
    incoming.set(edge.target, inEdges);
    const outEdges = outgoing.get(edge.source) ?? [];
    outEdges.push(edge);
    outgoing.set(edge.source, outEdges);
  }

  const matches = graph.nodes.filter((node) => {
    if (!focusedKinds.has(node.kind)) return false;
    if (!normalized) return true;
    return `${node.label} ${node.id} ${node.kind}`
      .toLocaleLowerCase()
      .includes(normalized);
  });
  const visible = new Set(matches.map((node) => node.id));
  visible.add(graph.principal);

  const walk = (
    initial: string[],
    adjacency: Map<string, GraphEdgeOut[]>,
    nextNode: (edge: GraphEdgeOut) => string,
  ) => {
    const queue = [...initial];
    while (queue.length > 0) {
      const nodeId = queue.shift()!;
      for (const edge of adjacency.get(nodeId) ?? []) {
        const neighbor = nextNode(edge);
        if (visible.has(neighbor)) continue;
        visible.add(neighbor);
        queue.push(neighbor);
      }
    }
  };

  walk(
    matches.map((node) => node.id),
    incoming,
    (edge) => edge.source,
  );
  walk(
    matches.map((node) => node.id),
    outgoing,
    (edge) => edge.target,
  );

  return {
    ...graph,
    nodes: graph.nodes.filter((node) => visible.has(node.id)),
    edges: graph.edges.filter(
      (edge) => visible.has(edge.source) && visible.has(edge.target),
    ),
  };
}
