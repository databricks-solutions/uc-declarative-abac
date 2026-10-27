import assert from "node:assert/strict";
import test from "node:test";
import type {
  GraphOut,
  InverseGraphOut,
} from "../../src/abac_viewer/ui/lib/api";
import {
  UNIFIED_NODE_KINDS,
  focusUnifiedGraph,
  hideMaskedPrincipals,
  withSelectedColumn,
} from "../../src/abac_viewer/ui/components/viewer/unified-graph";

const graph: GraphOut = {
  principal: "alice",
  nodes: [
    { id: "alice", kind: "user", label: "alice" },
    { id: "analysts", kind: "group", label: "analysts" },
    { id: "sales-policy", kind: "policy", label: "sales access" },
    { id: "sales-tag", kind: "tag", label: "domain=sales" },
    { id: "main.sales.orders", kind: "table", label: "main.sales.orders" },
    { id: "finance-policy", kind: "policy", label: "finance access" },
    { id: "finance-tag", kind: "tag", label: "domain=finance" },
    {
      id: "main.finance.budgets",
      kind: "table",
      label: "main.finance.budgets",
    },
  ],
  edges: [
    { source: "alice", target: "analysts", kind: "membership", label: "member" },
    { source: "analysts", target: "sales-policy", kind: "to", label: "in 'to'" },
    { source: "sales-policy", target: "sales-tag", kind: "matches", label: "matches" },
    { source: "sales-tag", target: "main.sales.orders", kind: "tagged", label: "SELECT" },
    { source: "analysts", target: "finance-policy", kind: "to", label: "in 'to'" },
    { source: "finance-policy", target: "finance-tag", kind: "matches", label: "matches" },
    { source: "finance-tag", target: "main.finance.budgets", kind: "tagged", label: "SELECT" },
  ],
};

test("returns the full live graph with no focus", () => {
  assert.equal(
    focusUnifiedGraph(graph, "", new Set(UNIFIED_NODE_KINDS)),
    graph,
  );
});

test("keeps the complete path to a matching table", () => {
  const focused = focusUnifiedGraph(
    graph,
    "orders",
    new Set(UNIFIED_NODE_KINDS),
  );

  assert.deepEqual(
    focused.nodes.map((node) => node.id),
    ["alice", "analysts", "sales-policy", "sales-tag", "main.sales.orders"],
  );
  assert.equal(focused.edges.length, 4);
});

test("kind focus preserves context around matching policies", () => {
  const focused = focusUnifiedGraph(graph, "sales", new Set(["policy"]));

  assert.deepEqual(
    focused.nodes.map((node) => node.id),
    ["alice", "analysts", "sales-policy", "sales-tag", "main.sales.orders"],
  );
});

test("a missing search leaves only the principal", () => {
  const focused = focusUnifiedGraph(
    graph,
    "does-not-exist",
    new Set(UNIFIED_NODE_KINDS),
  );

  assert.deepEqual(focused.nodes.map((node) => node.id), ["alice"]);
  assert.deepEqual(focused.edges, []);
});

test("adds a selected column after its table", () => {
  const selected = withSelectedColumn(graph, "main.sales.orders.customer_id");

  assert.deepEqual(selected.nodes.at(-1), {
    id: "main.sales.orders.customer_id",
    kind: "column",
    label: "customer_id",
  });
  assert.deepEqual(selected.edges.at(-1), {
    source: "main.sales.orders",
    target: "main.sales.orders.customer_id",
    kind: "contains",
    label: "column",
  });
  assert.equal(withSelectedColumn(graph, "main.missing.table.id"), graph);
});

test("carries an effective mask onto a selected access-graph column", () => {
  const selected = withSelectedColumn(
    graph,
    "main.sales.orders.customer_email",
    { masked: true },
  );
  const column = selected.nodes.at(-1);

  assert.equal(column?.kind, "column");
  assert.equal(column?.masked, true);
});

test("carries a targeted but unapplied mask onto a selected column", () => {
  const selected = withSelectedColumn(
    graph,
    "main.sales.orders.customer_email",
    { mask_targeted: true, masked: false },
  );
  const column = selected.nodes.at(-1);

  assert.equal(column?.mask_targeted, true);
  assert.equal(column?.masked, false);
});

test("hides masked principal roots but preserves shared path nodes", () => {
  const inverse: InverseGraphOut = {
    principal: "all",
    target: "main.sales.orders.email",
    target_type: "column",
    principal_effects: [
      {
        principal: "alice",
        principal_kind: "user",
        masked: true,
        row_filtered: false,
      },
      {
        principal: "bob",
        principal_kind: "user",
        masked: false,
        row_filtered: false,
      },
      {
        principal: "analysts",
        principal_kind: "group",
        masked: true,
        row_filtered: false,
      },
    ],
    nodes: [
      { id: "alice", kind: "user", label: "alice", effect_principal: true },
      { id: "bob", kind: "user", label: "bob", effect_principal: true },
      {
        id: "analysts",
        kind: "group",
        label: "analysts",
        effect_principal: true,
        masked: false,
      },
      { id: "policy", kind: "policy", label: "policy" },
      { id: "main.sales.orders", kind: "table", label: "orders" },
      {
        id: "main.sales.orders.email",
        kind: "column",
        label: "email",
      },
    ],
    edges: [
      { source: "alice", target: "analysts", kind: "membership", label: "member" },
      { source: "bob", target: "analysts", kind: "membership", label: "member" },
      { source: "analysts", target: "policy", kind: "to", label: "in 'to'" },
      { source: "policy", target: "main.sales.orders", kind: "grant", label: "SELECT" },
      { source: "main.sales.orders", target: "main.sales.orders.email", kind: "contains", label: "column" },
    ],
  };

  const visible = hideMaskedPrincipals(inverse, true);

  assert.deepEqual(
    visible.principal_effects.map((effect) => effect.principal),
    ["bob", "analysts"],
  );
  assert.equal(visible.nodes.some((node) => node.id === "alice"), false);
  assert.deepEqual(
    visible.nodes.find((node) => node.id === "analysts"),
    {
      id: "analysts",
      kind: "group",
      label: "analysts",
      effect_principal: true,
      masked: false,
    },
  );
});
