import assert from "node:assert/strict";
import test from "node:test";
import {
  patchViewerSearch,
  validateViewerSearch,
} from "../../src/abac_viewer/ui/components/viewer/viewer-url-state";

test("validates shareable viewer state", () => {
  assert.deepEqual(
    validateViewerSearch({
      tab: "tree",
      p: "analysts",
      q: "columns",
      hide: "false",
      table: "main.sales.orders",
      why: "column",
      target: "main.sales.orders.email",
      wp: "alice@example.com",
      mode: "steps",
      filterFlow: "0",
      cascade: "1",
    }),
    {
      tab: "tree",
      p: "analysts",
      q: "columns",
      hide: false,
      table: "main.sales.orders",
      why: "column",
      target: "main.sales.orders.email",
      wp: "alice@example.com",
      mode: "steps",
      filterFlow: false,
      cascade: true,
    },
  );
});

test("drops malformed and orphaned URL state", () => {
  assert.deepEqual(
    validateViewerSearch({
      tab: "admin",
      q: ["tables"],
      hide: "sometimes",
      why: "table",
      rowFilters: "true",
      target: "",
      traceType: "unknown",
    }),
    {},
  );
});

test("keeps table Why cascade visibility shareable", () => {
  assert.deepEqual(
    validateViewerSearch({
      why: "table",
      target: "main.sales.orders",
      cascade: "true",
    }),
    {
      why: "table",
      target: "main.sales.orders",
      cascade: true,
    },
  );
});

test("keeps unified explorer selection and search shareable", () => {
  assert.deepEqual(
    validateViewerSearch({
      tab: "unified",
      p: "alice@example.com",
      uNode: "main.sales.orders",
      uTarget: "main.sales.orders.email",
      uHideMasked: "false",
      uSearch: "sales",
      uEffect: "filter",
      uEffectTable: "main.sales.orders",
      uEffectColumn: "main.sales.orders.region",
      mode: "steps",
    }),
    {
      tab: "unified",
      p: "alice@example.com",
      uNode: "main.sales.orders",
      uTarget: "main.sales.orders.email",
      uHideMasked: false,
      uSearch: "sales",
      uEffect: "filter",
      uEffectTable: "main.sales.orders",
      uEffectColumn: "main.sales.orders.region",
      mode: "steps",
    },
  );
});

test("drops malformed unified explorer state", () => {
  assert.deepEqual(
    validateViewerSearch({
      tab: "unified",
      uNode: ["main.sales.orders"],
      uSearch: false,
      uEffect: "mask",
      uEffectColumn: "main.sales.orders.email",
    }),
    { tab: "unified" },
  );
});

test("patching removes undefined keys without losing other page state", () => {
  assert.deepEqual(
    patchViewerSearch(
      {
        tab: "explorer",
        p: "alice@example.com",
        why: "table",
        target: "main.sales.orders",
      },
      { why: undefined, target: undefined, q: "who" },
    ),
    {
      tab: "explorer",
      p: "alice@example.com",
      q: "who",
    },
  );
});
