import {
  useRouter,
  useRouterState,
} from "@tanstack/react-router";

export type ViewerTab = "explorer" | "tree" | "trace" | "unified";
export type ExplorerQuestion = "tables" | "columns" | "who";
export type WhyKind = "table" | "column";
export type DisplayMode = "graph" | "steps";
export type TracePolicyType = "grants" | "filters" | "masks";
export type TracePerspective = "principal" | "securable";
export type UnifiedEffect = "filter" | "mask";

export type ViewerSearch = {
  tab?: ViewerTab;
  p?: string;
  q?: ExplorerQuestion;
  column?: string;
  hide?: boolean;
  table?: string;
  why?: WhyKind;
  target?: string;
  wp?: string;
  maskFlow?: boolean;
  filterFlow?: boolean;
  tableAccess?: boolean;
  cascade?: boolean;
  mode?: DisplayMode;
  traceType?: TracePolicyType;
  tracePerspective?: TracePerspective;
  securable?: string;
  uNode?: string;
  uTarget?: string;
  uHideMasked?: boolean;
  uSearch?: string;
  uEffect?: UnifiedEffect;
  uEffectTable?: string;
  uEffectColumn?: string;
};

declare module "@tanstack/history" {
  interface HistoryState {
    abacOverlayFrom?: number;
  }
}

const TABS = new Set<ViewerTab>(["explorer", "tree", "trace", "unified"]);
const QUESTIONS = new Set<ExplorerQuestion>(["tables", "columns", "who"]);
const WHY_KINDS = new Set<WhyKind>(["table", "column"]);
const DISPLAY_MODES = new Set<DisplayMode>(["graph", "steps"]);
const TRACE_TYPES = new Set<TracePolicyType>(["grants", "filters", "masks"]);
const TRACE_PERSPECTIVES = new Set<TracePerspective>([
  "principal",
  "securable",
]);
const UNIFIED_EFFECTS = new Set<UnifiedEffect>(["filter", "mask"]);

function enumValue<T extends string>(value: unknown, values: Set<T>): T | undefined {
  return typeof value === "string" && values.has(value as T)
    ? (value as T)
    : undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function booleanValue(value: unknown): boolean | undefined {
  if (value === true || value === "true" || value === "1") return true;
  if (value === false || value === "false" || value === "0") return false;
  return undefined;
}

export function validateViewerSearch(
  search: Record<string, unknown>,
): ViewerSearch {
  const tab = enumValue(search.tab, TABS);
  const why = enumValue(search.why, WHY_KINDS);
  const target = stringValue(search.target);
  const validWhy = why && target ? why : undefined;
  const unifiedEffect = enumValue(search.uEffect, UNIFIED_EFFECTS);
  const unifiedEffectTable = stringValue(search.uEffectTable);
  const validUnifiedEffect =
    unifiedEffect && unifiedEffectTable ? unifiedEffect : undefined;

  return compactViewerSearch({
    tab,
    p: stringValue(search.p),
    q: enumValue(search.q, QUESTIONS),
    column: stringValue(search.column),
    hide: booleanValue(search.hide),
    table: stringValue(search.table),
    why: validWhy,
    target: validWhy ? target : undefined,
    wp: validWhy === "column" ? stringValue(search.wp) : undefined,
    maskFlow:
      validWhy === "column" ? booleanValue(search.maskFlow) : undefined,
    filterFlow:
      validWhy === "column" ? booleanValue(search.filterFlow) : undefined,
    tableAccess:
      validWhy === "column" ? booleanValue(search.tableAccess) : undefined,
    cascade: validWhy ? booleanValue(search.cascade) : undefined,
    mode: enumValue(search.mode, DISPLAY_MODES),
    traceType: enumValue(search.traceType, TRACE_TYPES),
    tracePerspective: enumValue(
      search.tracePerspective,
      TRACE_PERSPECTIVES,
    ),
    securable: stringValue(search.securable),
    uNode: stringValue(search.uNode),
    uTarget: stringValue(search.uTarget),
    uHideMasked: booleanValue(search.uHideMasked),
    uSearch: stringValue(search.uSearch),
    uEffect: validUnifiedEffect,
    uEffectTable: validUnifiedEffect ? unifiedEffectTable : undefined,
    uEffectColumn: validUnifiedEffect
      ? stringValue(search.uEffectColumn)
      : undefined,
  });
}

export function compactViewerSearch(search: ViewerSearch): ViewerSearch {
  return Object.fromEntries(
    Object.entries(search).filter(([, value]) => value !== undefined),
  ) as ViewerSearch;
}

export function patchViewerSearch(
  current: ViewerSearch,
  patch: Partial<ViewerSearch>,
): ViewerSearch {
  return compactViewerSearch({ ...current, ...patch });
}

const CLEAR_WHY: Partial<ViewerSearch> = {
  why: undefined,
  target: undefined,
  wp: undefined,
  maskFlow: undefined,
  filterFlow: undefined,
  tableAccess: undefined,
  cascade: undefined,
  mode: undefined,
};

export function useViewerUrlState() {
  const router = useRouter();
  const search = useRouterState({
    select: (state) => state.location.search as ViewerSearch,
  });
  const historyState = useRouterState({
    select: (state) => state.location.state,
  });

  const update = (
    patch: Partial<ViewerSearch>,
    options: { replace?: boolean } = {},
  ) =>
    router.navigate({
      to: "/",
      search: patchViewerSearch(search, patch),
      state: true,
      replace: options.replace,
      resetScroll: false,
    });

  const openWhy = (
    why: WhyKind,
    target: string,
    principal?: string,
    options: { replace?: boolean } = {},
  ) =>
    router.navigate({
      to: "/",
      search: patchViewerSearch(search, {
        ...CLEAR_WHY,
        why,
        target,
        wp: why === "column" ? principal : undefined,
      }),
      state: (current) => ({
        ...current,
        abacOverlayFrom:
          current.abacOverlayFrom ?? current.__TSR_index,
      }),
      replace: options.replace,
      resetScroll: false,
    });

  const closeWhy = () => {
    const from = historyState.abacOverlayFrom;
    if (from !== undefined && from < historyState.__TSR_index) {
      router.history.go(from - historyState.__TSR_index);
      return;
    }
    void update(CLEAR_WHY, { replace: true });
  };

  return {
    search,
    update,
    openWhy,
    closeWhy,
  };
}
