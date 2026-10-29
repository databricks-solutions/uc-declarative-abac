import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";

const chromePath =
  process.env.CHROME_PATH ??
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const port = Number(process.env.CDP_PORT ?? 9335);
const appUrl = process.env.APP_URL ?? "http://127.0.0.1:9001/";
const bearerToken = process.env.DATABRICKS_BEARER_TOKEN;
const screenshotPath = process.env.SCREENSHOT_PATH;
const effectScreenshotPath = process.env.EFFECT_SCREENSHOT_PATH;
const chrome = spawn(
  chromePath,
  [
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    "--disable-background-networking",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=/tmp/abac-unified-all-${process.pid}`,
    bearerToken ? "about:blank" : `${appUrl}?p=__all__`,
  ],
  { stdio: "ignore" },
);

const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

async function target() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then(
        (response) => response.json(),
      );
      const page = targets.find((candidate) => candidate.type === "page");
      if (page) return page;
    } catch {}
    await sleep(250);
  }
  throw new Error("Chrome DevTools target did not start");
}

const page = await target();
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let nextId = 1;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!message.id) return;
  const waiter = pending.get(message.id);
  if (!waiter) return;
  pending.delete(message.id);
  if (message.error) waiter.reject(new Error(message.error.message));
  else waiter.resolve(message.result);
});

function send(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) =>
    pending.set(id, {
      resolve,
      reject: (error) => reject(new Error(`${method}: ${error.message}`)),
    }),
  );
}

if (bearerToken) {
  await send("Network.enable");
  await send("Network.setExtraHTTPHeaders", {
    headers: { Authorization: `Bearer ${bearerToken}` },
  });
  await send("Page.navigate", { url: `${appUrl}?p=__all__` });
}
await send("Emulation.setDeviceMetricsOverride", {
  width: 1600,
  height: 1000,
  deviceScaleFactor: 1,
  mobile: false,
});
async function evaluate(expression) {
  const response = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.exceptionDetails) {
    throw new Error(`${response.exceptionDetails.text}\nExpression: ${expression}`);
  }
  return response.result.value;
}

async function waitFor(expression) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (await evaluate(expression)) return;
    await sleep(100);
  }
  throw new Error(`Timed out waiting for: ${expression}`);
}

async function click(expression) {
  const point = JSON.parse(
    await evaluate(`(() => {
      const element = ${expression};
      if (!element) throw new Error("Click target not found");
      element.scrollIntoView({ block: "center", inline: "center" });
      const rect = element.getBoundingClientRect();
      return JSON.stringify({
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
      });
    })()`),
  );
  await send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: point.x,
    y: point.y,
    button: "left",
    clickCount: 1,
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: point.x,
    y: point.y,
    button: "left",
    clickCount: 1,
  });
}

const table = "abac_viz_demo.sales.customers";
const tripsTable = "abac_viz_demo.sales.trips";
const effectPrincipal = "abac_demo_sp_ana_amer_1";
const effectGroup = "abac_demo_analysts";

try {
  if (screenshotPath || effectScreenshotPath) {
    await evaluate(`(() => {
      localStorage.setItem("apx-ui-theme", "light");
      if (!document.documentElement.classList.contains("light")) location.reload();
    })()`);
    await waitFor(`document.documentElement.classList.contains("light")`);
  }
  await waitFor(`document.body?.innerText.includes("Select a table or column")`);
  assert.equal(
    await evaluate(`Boolean(document.querySelector("[data-unified-access-graph]"))`),
    false,
    "All mode must not load a graph before a target is selected",
  );

  await click(`document.querySelector('button[aria-label="Expand all catalog branches"]')`);
  assert.equal(
    await evaluate(`document.querySelectorAll("[data-tree-column]").length`),
    0,
    "catalog expansion must not expand table columns",
  );

  const columnsButton = `document.querySelector('button[aria-label$="all columns for ${table}"]')`;
  await click(columnsButton);
  await waitFor(`document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]').length > 0`);
  assert.equal(
    await evaluate(`${columnsButton}.getAttribute("aria-pressed")`),
    "true",
  );
  assert.equal(
    await evaluate(`
      [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')]
        .find((column) => column.textContent.trim().startsWith("email"))
        .lastElementChild.textContent.trim()
    `),
    "MASKED",
    "All mode should mark columns targeted by mask policies",
  );
  assert.equal(
    await evaluate(`
      [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')]
        .find((column) => column.textContent.trim().startsWith("region"))
        .textContent.trim()
    `),
    "region",
    "All mode should not project row-filter policies onto input columns",
  );
  assert.equal(
    await evaluate(`${columnsButton}.closest('[role="treeitem"]').querySelector('[data-tree-status]').textContent.trim()`),
    "ROW FILTER POLICY (NOT APPLIED)",
    "All mode should roll row-filter policy presence up to the table",
  );

  await click(`${columnsButton}.closest('[role="treeitem"]').querySelector('button')`);
  await waitFor(`new URLSearchParams(location.search).get("uTarget") === ${JSON.stringify(table)}`);
  await waitFor(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${effectPrincipal}"]'))`);
  assert.equal(
    await evaluate(`document.querySelector('[data-node-id="${effectPrincipal}"]').getAttribute("data-node-filtered")`),
    "true",
  );
  assert.equal(
    await evaluate(`document.querySelector('[data-node-id="${effectPrincipal}"]').getAttribute("data-node-masked")`),
    "true",
  );
  assert.equal(
    await evaluate(`document.querySelectorAll('[data-node-id="${effectPrincipal}"] [data-effect-badge]').length`),
    2,
    "inverse principal nodes should use filter and mask badges",
  );
  assert.deepEqual(
    JSON.parse(
      await evaluate(`(() => {
        const node = document.querySelector('[data-unified-access-graph] [data-node-id="${effectPrincipal}"]');
        const filtered = node.querySelector('[data-node-effect="filtered"]');
        const masked = node.querySelector('[data-node-effect="masked"]');
        const columns = [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')];
        const maskBadge = columns.find((column) => column.textContent.trim().startsWith("email")).lastElementChild;
        const maskRect = masked.querySelector('[data-effect-badge]');
        return JSON.stringify({
          maskFillMatches: getComputedStyle(maskRect).fill === getComputedStyle(maskBadge).backgroundColor,
          maskBorderMatches: getComputedStyle(maskRect).stroke === getComputedStyle(maskBadge).borderColor,
          maskStrokeMatches: getComputedStyle(masked.querySelector('[data-effect-icon]')).stroke === getComputedStyle(maskBadge).color,
          filterSize: [filtered.querySelector('[data-effect-badge]').getAttribute("width"), filtered.querySelector('[data-effect-badge]').getAttribute("height")],
          maskSize: [maskRect.getAttribute("width"), maskRect.getAttribute("height")],
        });
      })()`),
    ),
    {
      maskFillMatches: true,
      maskBorderMatches: true,
      maskStrokeMatches: true,
      filterSize: ["24", "24"],
      maskSize: ["24", "24"],
    },
    "graph filter and mask icons should match the colored tree badges",
  );
  assert.equal(
    await evaluate(`document.querySelector('[data-unified-access-graph] [data-node-id="${effectGroup}"]').getAttribute("data-node-masked")`),
    null,
    "group nodes should not expose masked status",
  );
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${effectGroup}"] [data-node-effect="masked"]'))`),
    false,
    "group nodes should not render masked badges",
  );
  assert.equal(
    await evaluate(`document.querySelector('[data-unified-access-graph] [data-node-id="${effectGroup}"]').getAttribute("data-node-filtered")`),
    null,
    "group nodes should not expose row-filtered status",
  );
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${effectGroup}"] [data-node-effect="filtered"]'))`),
    false,
    "group nodes should not render row-filter badges",
  );

  const policyNode = `document.querySelector('[data-unified-access-graph] [data-node-id*="grant_gold_analysts"]')`;
  assert.equal(
    await evaluate(`${policyNode}.tagName.toLowerCase()`),
    "g",
    "inverse policy nodes must inspect in-app instead of linking directly",
  );
  await click(policyNode);
  await waitFor(`document.querySelector('[data-unified-panel="details"]')?.innerText.includes("POLICY")`);
  await waitFor(`Boolean(document.querySelector('[data-unified-panel="details"] [data-node-code-link]'))`);
  assert.equal(
    await evaluate(`location.pathname`),
    new URL(appUrl).pathname,
    "inspecting an inverse policy must not navigate away from the app",
  );

  const tagNode = `document.querySelector('[data-unified-access-graph] [data-node-id^="tag:"]')`;
  assert.equal(
    await evaluate(`${tagNode}.tagName.toLowerCase()`),
    "g",
    "inverse tag nodes must inspect in-app instead of linking directly",
  );
  await click(tagNode);
  await waitFor(`document.querySelector('[data-unified-panel="details"]')?.innerText.includes("TAG")`);
  await waitFor(`Boolean(document.querySelector('[data-unified-panel="details"] [data-edge-code-link]'))`);

  await click(`document.querySelector('[data-node-id="${effectPrincipal}"]')`);
  await waitFor(`document.querySelector('[data-all-principal-effects]')?.innerText.includes("Row filter Why")`);
  await waitFor(`document.querySelector('[data-all-principal-effects]')?.innerText.includes("Mask Why")`);
  await waitFor(`document.querySelectorAll('[data-all-principal-effects] [data-graph-node]').length > 0`);
  assert.equal(
    await evaluate(`(() => {
      const list = document.querySelector('[data-principal-effect-list]');
      const width = list.getBoundingClientRect().width;
      return [...list.querySelectorAll('[data-principal-effect-why]')]
        .every((item) => Math.abs(item.getBoundingClientRect().width - width) < 2);
    })()`),
    true,
    "filter and mask Why graphs should use the full available width",
  );
  await click(`document.querySelector('[data-unified-access-graph] [data-node-id="${effectGroup}"]')`);
  await waitFor(`document.querySelector('[data-all-principal-effects]')?.innerText.includes("${effectGroup}")`);
  assert.equal(
    await evaluate(`document.querySelector('[data-all-principal-effects]').innerText.includes("Mask Why")`),
    false,
    "groups should not show Mask Why",
  );
  assert.equal(
    await evaluate(`document.querySelector('[data-all-principal-effects]').innerText.includes("Row filter Why")`),
    false,
    "groups should not show Row Filter Why",
  );

  await click(`
    [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')]
      .find((column) => column.textContent.trim().startsWith("email"))
  `);
  await waitFor(`new URLSearchParams(location.search).get("uTarget") === ${JSON.stringify(`${table}.email`)}`);
  await waitFor(`document.querySelector('[data-unified-access-graph]')?.innerText.includes(${JSON.stringify(`${table}.email`)})`);
  await waitFor(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${table}.email"]'))`);
  assert.equal(
    await evaluate(`document.querySelector('[aria-label="Hide principals with masked column access"]').getAttribute("aria-checked")`),
    "true",
    "masked principals should be hidden by default for column targets",
  );
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${effectPrincipal}"]'))`),
    false,
    "a principal with masked access should be hidden by default",
  );
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${effectGroup}"]'))`),
    true,
    "Hide masked should retain group access paths",
  );
  const exemptPrincipal = "abac_demo_sp_eng_1";
  await waitFor(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${exemptPrincipal}"]'))`);
  await click(`document.querySelector('[data-unified-access-graph] [data-node-id="${exemptPrincipal}"]')`);
  await waitFor(`document.querySelector('[data-all-principal-effects]')?.innerText.includes("Row filter Why")`);
  await waitFor(`document.querySelector('[data-all-principal-effects]')?.innerText.includes("Mask Why")`);
  await waitFor(`
    [...document.querySelectorAll("[data-all-principal-effects] path[data-edge-label]")]
      .filter((edge) => edge.getAttribute("data-edge-label") === "in 'except' (exempt)")
      .length >= 2
  `);
  if (screenshotPath) {
    await send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: 1580,
      y: 980,
    });
    await sleep(200);
    const screenshot = await send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
    });
    await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  }
  await click(`document.querySelector('[aria-label="Hide principals with masked column access"]')`);
  await waitFor(`document.querySelector('[aria-label="Hide principals with masked column access"]').getAttribute("aria-checked") === "false"`);
  await waitFor(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${effectPrincipal}"]'))`);
  assert.deepEqual(
    JSON.parse(
      await evaluate(`(() => {
        const edge = document.querySelector('[data-unified-access-graph] path[data-edge-kind="contains"]');
        const markerId = edge.getAttribute("marker-end").match(/#([^)]*)/)[1];
        const marker = document.getElementById(markerId);
        return JSON.stringify({
          width: marker.getAttribute("markerWidth"),
          units: marker.getAttribute("markerUnits"),
        });
      })()`),
    ),
    { width: "6", units: "userSpaceOnUse" },
    "column arrows should keep one small fixed size",
  );
  await click(`document.querySelector('[data-node-id="${effectPrincipal}"]')`);
  await waitFor(`document.querySelector('[data-all-principal-effects]')?.innerText.includes("Row filter Why")`);
  await waitFor(`document.querySelector('[data-all-principal-effects]')?.innerText.includes("Mask Why")`);

  await evaluate(`location.href = ${JSON.stringify(appUrl)} + "?p=${effectPrincipal}"`);
  await waitFor(`Boolean(document.querySelector('button[aria-label="Show row filter Why for ${table}"]'))`);
  await click(`document.querySelector('button[aria-label="Show all columns for ${table}"]')`);
  await waitFor(`Boolean(document.querySelector('[aria-label="Columns for ${table}"]'))`);
  await click(`
    [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')]
      .find((column) => column.textContent.trim().startsWith("email"))
  `);
  await waitFor(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${table}.email"]'))`);
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[aria-label="Columns for ${table}"]'))`),
    true,
    "selecting a masked column must keep the all-columns list",
  );
  assert.equal(
    await evaluate(`
      [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')]
        .some((column) => column.textContent.trim().startsWith("customer_id"))
    `),
    true,
    "selecting a masked column must keep non-masked columns visible",
  );
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[aria-label="Masked columns for ${table}"]'))`),
    false,
    "selecting a masked column must not add a duplicate masked-columns list",
  );
  await waitFor(`document.querySelector('[data-unified-inline-why]')?.innerText.includes("Mask Why")`);
  await click(`document.querySelector('button[aria-label="Show row filter Why for ${table}"]')`);
  await waitFor(`document.querySelector('[data-unified-inline-why]')?.innerText.includes("Row filter Why")`);
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[aria-label="Columns for ${table}"]'))`),
    false,
    "opening table-level Row filter Why should close the all-columns list",
  );
  await waitFor(`document.querySelectorAll('[data-unified-inline-why] [data-graph-node]').length > 0`);
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${table}.region"]'))`),
    false,
    "table-level row filtering must not add a predicate column to the access graph",
  );

  await click(`document.querySelector('button[aria-label="Show masked columns for ${table}"]')`);
  await waitFor(`Boolean(document.querySelector('[aria-label="Masked columns for ${table}"] [data-tree-effect-column]'))`);
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[aria-label="Columns for ${table}"]'))`),
    false,
    "masked columns must replace the all-columns list",
  );
  assert.equal(
    await evaluate(`document.querySelector('[aria-label="Masked columns for ${table}"] [data-tree-effect-column]').lastElementChild.textContent.trim()`),
    "MASKED",
    "masked icons should stay on the right of column labels",
  );
  await click(`document.querySelector('[aria-label="Masked columns for ${table}"] [data-tree-effect-column]')`);
  await waitFor(`document.querySelector('[data-unified-inline-why]')?.innerText.includes("Mask Why")`);
  await waitFor(`document.querySelectorAll('[data-unified-inline-why] [data-graph-node]').length > 0`);
  await waitFor(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${table}.email"]'))`);
  if (effectScreenshotPath) {
    await send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: 1580,
      y: 980,
    });
    await sleep(200);
    const screenshot = await send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
    });
    await writeFile(effectScreenshotPath, Buffer.from(screenshot.data, "base64"));
  }

  await evaluate(`location.href = ${JSON.stringify(appUrl)} + "?p=${effectPrincipal}"`);
  await waitFor(`Boolean(document.querySelector('button[aria-label="Show row filter Why for ${tripsTable}"]'))`);
  const tripsGraphFilter = `document.querySelector('[data-unified-access-graph] [data-node-id="${tripsTable}"] [data-node-effect="filtered"]')`;
  await waitFor(`Boolean(${tripsGraphFilter})`);
  await click(tripsGraphFilter);
  await waitFor(`document.querySelector('[data-unified-inline-why]')?.innerText.includes("Row filter Why")`);
  await waitFor(`Boolean(document.querySelector('[data-unified-inline-why] [data-node-id="${tripsTable}.from_region"]'))`);
  assert.equal(
    await evaluate(`[
      ${JSON.stringify(tripsTable)},
      ${JSON.stringify(`${tripsTable}.from_region`)},
      ${JSON.stringify(`${tripsTable}.to_region`)},
      "tag:abac_demo_sensitivity=high",
      "tag:abac_demo_trips=trip",
      "tag:abac_demo_from_region=region",
      "tag:abac_demo_to_region=region"
    ].every((id) => Boolean(document.querySelector('[data-unified-inline-why] [data-node-id="' + id + '"]')))`),
    true,
    "trip Row filter Why should show both table tags and both predicate-column tags",
  );
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${tripsTable}"] [data-node-effect="filtered"]'))`),
    true,
    "the access graph should put the filter icon on the trips table",
  );
  assert.equal(
    await evaluate(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${tripsTable}.from_region"]'))`),
    false,
    "the access graph should not add row-filter predicate columns",
  );
  await click(`document.querySelector('[data-unified-inline-why] [data-node-id="${tripsTable}"]')`);
  await waitFor(`Boolean(document.querySelector('[data-unified-panel="details"] [data-node-code-link]'))`);
  await click(`document.querySelector('[data-unified-inline-why] [data-node-id="tag:abac_demo_from_region=region"]')`);
  await waitFor(`Boolean(document.querySelector('[data-unified-panel="details"] [data-edge-code-link]'))`);

  await evaluate(`location.href = ${JSON.stringify(appUrl)} + "?p=abac_demo_sp_eng_1"`);
  await waitFor(`Boolean(document.querySelector('button[aria-label="Show all columns for ${table}"]'))`);
  assert.equal(
    await evaluate(`document.querySelector('button[aria-label="Show row filter Why for ${table}"]').textContent.trim()`),
    "ROW FILTER POLICY (NOT APPLIED)",
    "table filter controls should distinguish exempt principals from filtered ones",
  );
  assert.equal(
    await evaluate(`document.querySelector('button[aria-label="Show masked columns for ${table}"]').textContent.trim()`),
    "MASK POLICY (NOT APPLIED)",
    "table mask controls should gray mask policies that do not apply",
  );
  await click(`document.querySelector('button[aria-label="Show masked columns for ${table}"]')`);
  await waitFor(`Boolean(document.querySelector('[aria-label="Masked columns for ${table}"] [data-tree-effect-column]'))`);
  assert.equal(
    await evaluate(`document.querySelector('[aria-label="Masked columns for ${table}"] [data-tree-effect-column]').lastElementChild.textContent.trim()`),
    "MASK POLICY (NOT APPLIED)",
    "mask-policy subset lists should gray icons for exempt principals",
  );
  await click(`document.querySelector('button[aria-label="Hide masked columns for ${table}"]')`);
  await waitFor(`!document.querySelector('[aria-label="Masked columns for ${table}"]')`);
  await click(`document.querySelector('button[aria-label="Show all columns for ${table}"]')`);
  await waitFor(`Boolean(document.querySelector('[aria-label="Columns for ${table}"]'))`);
  const exemptEmailColumn = `
    [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')]
      .find((column) => column.textContent.trim().startsWith("email"))
  `;
  const exemptRegionColumn = `
    [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')]
      .find((column) => column.textContent.trim().startsWith("region"))
  `;
  assert.equal(
    await evaluate(`${exemptEmailColumn}.lastElementChild.textContent.trim()`),
    "MASK POLICY (NOT APPLIED)",
    "full column lists should gray unapplied mask-policy targets",
  );
  await click(exemptEmailColumn);
  await waitFor(`document.querySelector('[data-unified-inline-why]')?.innerText.includes("Mask Why")`);
  await waitFor(`Boolean(document.querySelector('[data-unified-access-graph] [data-node-id="${table}.email"] [data-node-effect="masked"]'))`);
  assert.equal(
    await evaluate(`document.querySelector('[data-unified-access-graph] [data-node-id="${table}.email"] [data-node-effect="masked"]').getAttribute("data-effect-applied")`),
    null,
    "the access graph should gray a targeted mask that does not apply",
  );
  assert.equal(
    await evaluate(`(() => {
      const graphBadge = document.querySelector('[data-unified-access-graph] [data-node-id="${table}.email"] [data-effect-badge]');
      const treeBadge = (${exemptEmailColumn}).lastElementChild;
      return getComputedStyle(graphBadge).fill === getComputedStyle(treeBadge).backgroundColor;
    })()`),
    true,
    "the gray graph mask icon should match the tree icon",
  );
  await waitFor(`document.querySelector('[data-mask-exemption]')?.innerText.includes("Exempt from masking")`);
  assert.equal(
    await evaluate(`document.querySelector('[data-mask-exemption]').innerText.includes("${exemptPrincipal}")`),
    true,
    "Mask Why should name the exempt principal",
  );
  assert.equal(
    await evaluate(`document.querySelector('[data-mask-exemption]').innerText.includes("abac_demo_data_platform")`),
    true,
    "Mask Why should name the matching exception path",
  );
  await waitFor(`
    [...document.querySelectorAll("[data-unified-inline-why] path[data-edge-label]")]
      .some((edge) => edge.getAttribute("data-edge-label") === "in 'except' (exempt)")
  `);
  assert.equal(
    await evaluate(`${exemptRegionColumn}.textContent.trim()`),
    "region",
    "full column lists should not show row-filter icons on predicate inputs",
  );
  const exemptGraphFilter = `document.querySelector('[data-unified-access-graph] [data-node-id="${table}"] [data-node-effect="filtered"]')`;
  assert.equal(
    await evaluate(`${exemptGraphFilter}.getAttribute("data-effect-applied")`),
    null,
    "the access graph should gray a targeted row filter that does not apply",
  );
  assert.equal(
    await evaluate(`(() => {
      const graphBadge = ${exemptGraphFilter}.querySelector('[data-effect-badge]');
      const treeBadge = document.querySelector('button[aria-label="Show row filter Why for ${table}"]').firstElementChild;
      return getComputedStyle(graphBadge).fill === getComputedStyle(treeBadge).backgroundColor;
    })()`),
    true,
    "the gray graph filter icon should match the tree icon",
  );
  await click(exemptGraphFilter);
  await waitFor(`document.querySelector('[data-unified-inline-why]')?.innerText.includes("Row filter Why")`);
  await waitFor(`document.querySelector('[data-filter-exemption]')?.innerText.includes("Exempt from row filtering")`);
  assert.equal(
    await evaluate(`document.querySelector('[data-filter-exemption]').innerText.includes("abac_demo_data_platform")`),
    true,
    "Row filter Why should name the matching exception path",
  );
  await waitFor(`
    [...document.querySelectorAll("[data-unified-inline-why] path[data-edge-label]")]
      .some((edge) => edge.getAttribute("data-edge-label") === "in 'except' (exempt)")
  `);
  await click(`
    document.querySelector('button[aria-label="Show all columns for abac_viz_demo.sales.orders"]')
      .closest('[role="treeitem"]')
      .querySelector('button')
  `);
  await waitFor(`
    new URLSearchParams(location.search).get("uNode") === "abac_viz_demo.sales.orders" &&
      !new URLSearchParams(location.search).has("uEffect") &&
      !document.querySelector('[data-unified-inline-why]')
  `);

  const vendorsColumn = "abac_viz_demo.finance.vendors.contact_email";
  const multiPrincipal = "abac_demo_sp_multi_1";
  await evaluate(`location.href = ${JSON.stringify(appUrl)} + ${JSON.stringify(
    `?p=__all__&uTarget=${vendorsColumn}&uNode=${multiPrincipal}&uHideMasked=false`,
  )}`);
  await waitFor(`document.querySelector('[data-all-principal-effects]')?.innerText.includes("Mask Why")`);
  const maskPolicyNode = `document.querySelector('[data-all-principal-effects] [data-node-label="mask_pii_contact"]')`;
  await waitFor(`Boolean(${maskPolicyNode})`);
  await click(maskPolicyNode);
  await waitFor(`document.querySelector('[data-unified-panel="details"]')?.innerText.includes("mask_pii_contact")`);
  await waitFor(`document.querySelector('[data-unified-panel="details"]')?.innerText.includes("POLICY")`);
  await waitFor(`Boolean(document.querySelector('[data-unified-panel="details"] [data-node-code-link]'))`);
  assert.equal(
    await evaluate(`new URLSearchParams(location.search).get("uNode")`),
    multiPrincipal,
    "inspecting a Mask Why node must preserve the selected principal",
  );
  assert.equal(
    await evaluate(`${maskPolicyNode}.getAttribute("aria-current")`),
    "true",
    "the selected Mask Why node should be highlighted",
  );

  const reportedUrlState =
    "?p=abac_demo_sp_eng_1&uHideMasked=true&uNode=abac_viz_demo.sales.customers&uEffect=mask&uEffectTable=abac_viz_demo.finance.vendors&uTarget=abac_viz_demo.finance.vendors.contact_email&uEffectColumn=abac_viz_demo.finance.vendors.contact_email";
  await evaluate(`location.href = ${JSON.stringify(appUrl)} + ${JSON.stringify(reportedUrlState)}`);
  await waitFor(`Boolean(document.querySelector('[aria-label="Masked columns for abac_viz_demo.finance.vendors"] [data-tree-effect-column]'))`);
  assert.equal(
    await evaluate(`document.querySelector('[aria-label="Masked columns for abac_viz_demo.finance.vendors"] [data-tree-effect-column]').lastElementChild.textContent.trim()`),
    "MASK POLICY (NOT APPLIED)",
    "the reported vendors mask subset should gray an unapplied mask policy",
  );
  await waitFor(`Boolean(document.querySelector('button[aria-label="Show all columns for ${table}"]'))`);
  await click(`document.querySelector('button[aria-label="Show all columns for ${table}"]')`);
  await waitFor(`Boolean(document.querySelector('[aria-label="Columns for ${table}"]'))`);
  assert.equal(
    await evaluate(`
      [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')]
        .find((column) => column.textContent.trim().startsWith("email"))
        .lastElementChild.textContent.trim()
    `),
    "MASK POLICY (NOT APPLIED)",
    "the reported customers email row should gray an unapplied mask policy",
  );
  assert.equal(
    await evaluate(`
      [...document.querySelectorAll('[aria-label="Columns for ${table}"] [data-tree-column]')]
        .find((column) => column.textContent.trim().startsWith("region"))
        .textContent.trim()
    `),
    "region",
    "the reported customers region row should not carry a filter icon",
  );

  const driftTable = "abac_viz_demo.sales.orders";
  const driftStart = `?p=${effectPrincipal}&uNode=${driftTable}`;
  await evaluate(`location.href = ${JSON.stringify(appUrl)} + ${JSON.stringify(driftStart)}`);
  await waitFor(`Boolean(document.querySelector("[data-warnings-toggle]"))`);
  await click(`document.querySelector("[data-warnings-toggle]")`);
  await waitFor(`Boolean(document.querySelector("[data-drift-link]"))`);
  await click(`document.querySelector("[data-drift-link]")`);
  await waitFor(`new URLSearchParams(location.search).get("p") === ${JSON.stringify(effectGroup)}`);
  await sleep(500);
  assert.equal(
    await evaluate(`new URLSearchParams(location.search).get("uNode")`),
    driftTable,
    "a drift link to the securable already selected under another principal must keep it selected",
  );

  console.log("unified All-principals browser checks passed");
} finally {
  socket.close();
  chrome.kill("SIGTERM");
}
