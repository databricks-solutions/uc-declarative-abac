import { useQuery, useSuspenseQuery, useMutation } from "@tanstack/react-query";
import type { UseQueryOptions, UseSuspenseQueryOptions, UseMutationOptions } from "@tanstack/react-query";
export class ApiError extends Error {
    status: number;
    statusText: string;
    body: unknown;
    constructor(status: number, statusText: string, body: unknown){
        super(`HTTP ${status}: ${statusText}`);
        this.name = "ApiError";
        this.status = status;
        this.statusText = statusText;
        this.body = body;
    }
}
export interface AccessRowOut {
    masked_columns: string[];
    row_filtered: boolean;
    securable: string;
    securable_type: string;
    status: string;
    tags: Record<string, string>;
}
export interface ChainGraphEdgeOut {
    code_sources?: GraphSourceOut[];
    kind: string;
    label: string;
    source: string;
    target: string;
}
export interface ChainGraphNodeOut {
    effect_principal?: boolean;
    github_url?: string | null;
    id: string;
    kind: string;
    label: string;
    layer: number;
    mask_targeted?: boolean;
    masked?: boolean;
    row_filter_targeted?: boolean;
    row_filtered?: boolean;
    source?: string | null;
    sublabel?: string;
}
export interface ChainGraphOut {
    edges: ChainGraphEdgeOut[];
    nodes: ChainGraphNodeOut[];
    principal: string;
    securable: string;
}
export interface ChainGroupOut {
    effects: ChainNodeOut[];
    membership: ChainNodeOut;
    policy: ChainNodeOut;
    tag: ChainNodeOut | null;
}
export interface ChainNodeOut {
    detail?: string;
    kind: string;
    label: string;
    source?: string | null;
}
export interface ColumnAccessRowOut {
    can_read_table: boolean;
    column: string;
    column_full_name: string;
    data_type: string | null;
    mask_targeted: boolean;
    masked: boolean;
    policy_name?: string | null;
    principal: string;
    row_filter_targeted: boolean;
    row_filtered: boolean;
    table: string;
    tags?: Record<string, string>;
}
export interface ColumnExplanationOut {
    arguments: PolicyArgumentOut[];
    can_read_table: boolean;
    column: string;
    column_full_name: string;
    covered_by: string | null;
    data_type: string | null;
    excepted_by: string | null;
    function: string | null;
    masked: boolean;
    policy_attached_level: string | null;
    policy_attached_to: string | null;
    policy_name: string | null;
    policy_source: string | null;
    principal: string;
    row_filter_excepted_by: string | null;
    row_filter_targeted: boolean;
    row_filtered: boolean;
    sentence: string;
    table_full_name: string;
    tag_atoms: Record<string, string>;
}
export interface ColumnPolicyOut {
    column_full_name: string;
    mask_policy_count?: number;
    row_filter_policy_count?: number;
}
export interface ColumnVerdictOut {
    column: string;
    data_type: string | null;
    mask_policy_ids: string[];
    masked: boolean;
}
export interface ComplexValue {
    display?: string | null;
    primary?: boolean | null;
    ref?: string | null;
    type?: string | null;
    value?: string | null;
}
export interface DriftOut {
    policy_id: string;
    policy_name: string;
    principal: string;
    privilege: string;
    securable: string;
    securable_type: string;
}
export interface GraphEdgeOut {
    code_sources?: GraphSourceOut[];
    kind: string;
    label: string;
    policy_id?: string | null;
    source: string;
    target: string;
}
export interface GraphNodeOut {
    effect_principal?: boolean;
    github_url?: string | null;
    id: string;
    kind: string;
    label: string;
    mask_targeted?: boolean;
    masked?: boolean;
    row_filter_targeted?: boolean;
    row_filtered?: boolean;
    source?: string | null;
}
export interface GraphOut {
    edges: GraphEdgeOut[];
    nodes: GraphNodeOut[];
    principal: string;
}
export interface GraphSourceOut {
    github_url?: string | null;
    inherited?: boolean;
    securable: string;
    securable_type: string;
    source?: string | null;
}
export interface HTTPValidationError {
    detail?: ValidationError[];
}
export interface InverseGraphOut {
    edges: GraphEdgeOut[];
    nodes: GraphNodeOut[];
    principal: string;
    principal_effects: PrincipalEffectOut[];
    target: string;
    target_type: string;
}
export interface MetaOut {
    build_sha: string;
    config_path_prefix: string;
    drift: DriftOut[];
    policies: number;
    principals: number;
    repo_slug: string;
    revision: string;
    securables: number;
    source: string;
    tables: number;
    warnings: string[];
}
export interface Name {
    family_name?: string | null;
    given_name?: string | null;
}
export interface PolicyArgumentOut {
    alias: string | null;
    constant: boolean | number | number | string | null;
    constant_type: string | null;
    kind: string;
    matched_columns: string[];
    position: number;
    target: boolean;
}
export interface PrincipalEffectOut {
    mask_policy_columns?: string[];
    mask_targeted?: boolean;
    masked: boolean;
    masked_columns?: string[];
    principal: string;
    principal_kind: string;
    row_filter_columns?: string[];
    row_filter_policy_columns?: string[];
    row_filter_targeted?: boolean;
    row_filtered: boolean;
}
export interface PrincipalOut {
    groups: string[];
    kind: string;
    name: string;
}
export interface TreeNodeOut {
    children?: TreeNodeOut[];
    column_count?: number | null;
    full_name: string;
    mask_policy_column_count?: number | null;
    masked_column_count?: number | null;
    name: string;
    readable?: boolean | null;
    row_filter_targeted?: boolean | null;
    row_filtered?: boolean | null;
    securable_type: string;
}
export interface User {
    active?: boolean | null;
    display_name?: string | null;
    emails?: ComplexValue[] | null;
    entitlements?: ComplexValue[] | null;
    external_id?: string | null;
    groups?: ComplexValue[] | null;
    id?: string | null;
    name?: Name | null;
    roles?: ComplexValue[] | null;
    schemas?: UserSchema[] | null;
    user_name?: string | null;
}
export const UserSchema = {
    "urn:ietf:params:scim:schemas:core:2.0:User": "urn:ietf:params:scim:schemas:core:2.0:User",
    "urn:ietf:params:scim:schemas:extension:workspace:2.0:User": "urn:ietf:params:scim:schemas:extension:workspace:2.0:User"
} as const;
export type UserSchema = typeof UserSchema[keyof typeof UserSchema];
export interface ValidationError {
    ctx?: Record<string, unknown>;
    input?: unknown;
    loc: (string | number)[];
    msg: string;
    type: string;
}
export interface VerdictOut {
    can_read: boolean;
    chains: ChainNodeOut[][];
    columns: ColumnVerdictOut[];
    groups: ChainGroupOut[];
    missing: string[];
    principal: string;
    row_filter_excepted_by: string | null;
    row_filter_targeted: boolean;
    row_filtered: boolean;
    securable: string;
    sentence: string;
    status: string;
}
export interface VersionOut {
    version: string;
}
export interface WhoAmIOut {
    groups: string[];
    known: boolean;
    principal: string;
}
export interface AccessForPrincipalParams {
    principal: string;
}
export const accessForPrincipal = async (params: AccessForPrincipalParams, options?: RequestInit): Promise<{
    data: AccessRowOut[];
}> =>{
    const searchParams = new URLSearchParams();
    if (params.principal != null) searchParams.set("principal", String(params.principal));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/access?${queryString}` : "/api/access";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const accessForPrincipalKey = (params?: AccessForPrincipalParams)=>{
    return [
        "/api/access",
        params
    ] as const;
};
export function useAccessForPrincipal<TData = {
    data: AccessRowOut[];
}>(options: {
    params: AccessForPrincipalParams;
    query?: Omit<UseQueryOptions<{
        data: AccessRowOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: accessForPrincipalKey(options.params),
        queryFn: ()=>accessForPrincipal(options.params),
        ...options?.query
    });
}
export function useAccessForPrincipalSuspense<TData = {
    data: AccessRowOut[];
}>(options: {
    params: AccessForPrincipalParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: AccessRowOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: accessForPrincipalKey(options.params),
        queryFn: ()=>accessForPrincipal(options.params),
        ...options?.query
    });
}
export const listColumns = async (options?: RequestInit): Promise<{
    data: string[];
}> =>{
    const res = await fetch("/api/column-names", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listColumnsKey = ()=>{
    return [
        "/api/column-names"
    ] as const;
};
export function useListColumns<TData = {
    data: string[];
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: string[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listColumnsKey(),
        queryFn: ()=>listColumns(),
        ...options?.query
    });
}
export function useListColumnsSuspense<TData = {
    data: string[];
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: string[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listColumnsKey(),
        queryFn: ()=>listColumns(),
        ...options?.query
    });
}
export const listColumnPolicies = async (options?: RequestInit): Promise<{
    data: ColumnPolicyOut[];
}> =>{
    const res = await fetch("/api/column-policies", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listColumnPoliciesKey = ()=>{
    return [
        "/api/column-policies"
    ] as const;
};
export function useListColumnPolicies<TData = {
    data: ColumnPolicyOut[];
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: ColumnPolicyOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listColumnPoliciesKey(),
        queryFn: ()=>listColumnPolicies(),
        ...options?.query
    });
}
export function useListColumnPoliciesSuspense<TData = {
    data: ColumnPolicyOut[];
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: ColumnPolicyOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listColumnPoliciesKey(),
        queryFn: ()=>listColumnPolicies(),
        ...options?.query
    });
}
export interface ColumnsForPrincipalParams {
    principal: string;
    filter?: "all" | "masked" | "unmasked";
    table?: string | null;
    include_inaccessible?: boolean;
}
export const columnsForPrincipal = async (params: ColumnsForPrincipalParams, options?: RequestInit): Promise<{
    data: ColumnAccessRowOut[];
}> =>{
    const searchParams = new URLSearchParams();
    if (params.principal != null) searchParams.set("principal", String(params.principal));
    if (params?.filter != null) searchParams.set("filter", String(params?.filter));
    if (params?.table != null) searchParams.set("table", String(params?.table));
    if (params?.include_inaccessible != null) searchParams.set("include_inaccessible", String(params?.include_inaccessible));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/columns?${queryString}` : "/api/columns";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const columnsForPrincipalKey = (params?: ColumnsForPrincipalParams)=>{
    return [
        "/api/columns",
        params
    ] as const;
};
export function useColumnsForPrincipal<TData = {
    data: ColumnAccessRowOut[];
}>(options: {
    params: ColumnsForPrincipalParams;
    query?: Omit<UseQueryOptions<{
        data: ColumnAccessRowOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: columnsForPrincipalKey(options.params),
        queryFn: ()=>columnsForPrincipal(options.params),
        ...options?.query
    });
}
export function useColumnsForPrincipalSuspense<TData = {
    data: ColumnAccessRowOut[];
}>(options: {
    params: ColumnsForPrincipalParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: ColumnAccessRowOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: columnsForPrincipalKey(options.params),
        queryFn: ()=>columnsForPrincipal(options.params),
        ...options?.query
    });
}
export interface CurrentUserParams {
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const currentUser = async (params?: CurrentUserParams, options?: RequestInit): Promise<{
    data: User;
}> =>{
    const res = await fetch("/api/current-user", {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const currentUserKey = (params?: CurrentUserParams)=>{
    return [
        "/api/current-user",
        params
    ] as const;
};
export function useCurrentUser<TData = {
    data: User;
}>(options?: {
    params?: CurrentUserParams;
    query?: Omit<UseQueryOptions<{
        data: User;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: currentUserKey(options?.params),
        queryFn: ()=>currentUser(options?.params),
        ...options?.query
    });
}
export function useCurrentUserSuspense<TData = {
    data: User;
}>(options?: {
    params?: CurrentUserParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: User;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: currentUserKey(options?.params),
        queryFn: ()=>currentUser(options?.params),
        ...options?.query
    });
}
export interface ExplainParams {
    principal: string;
    table: string;
}
export const explain = async (params: ExplainParams, options?: RequestInit): Promise<{
    data: VerdictOut;
}> =>{
    const searchParams = new URLSearchParams();
    if (params.principal != null) searchParams.set("principal", String(params.principal));
    if (params.table != null) searchParams.set("table", String(params.table));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/explain?${queryString}` : "/api/explain";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const explainKey = (params?: ExplainParams)=>{
    return [
        "/api/explain",
        params
    ] as const;
};
export function useExplain<TData = {
    data: VerdictOut;
}>(options: {
    params: ExplainParams;
    query?: Omit<UseQueryOptions<{
        data: VerdictOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: explainKey(options.params),
        queryFn: ()=>explain(options.params),
        ...options?.query
    });
}
export function useExplainSuspense<TData = {
    data: VerdictOut;
}>(options: {
    params: ExplainParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: VerdictOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: explainKey(options.params),
        queryFn: ()=>explain(options.params),
        ...options?.query
    });
}
export interface ExplainColumnParams {
    principal: string;
    column: string;
}
export const explainColumn = async (params: ExplainColumnParams, options?: RequestInit): Promise<{
    data: ColumnExplanationOut;
}> =>{
    const searchParams = new URLSearchParams();
    if (params.principal != null) searchParams.set("principal", String(params.principal));
    if (params.column != null) searchParams.set("column", String(params.column));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/explain-column?${queryString}` : "/api/explain-column";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const explainColumnKey = (params?: ExplainColumnParams)=>{
    return [
        "/api/explain-column",
        params
    ] as const;
};
export function useExplainColumn<TData = {
    data: ColumnExplanationOut;
}>(options: {
    params: ExplainColumnParams;
    query?: Omit<UseQueryOptions<{
        data: ColumnExplanationOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: explainColumnKey(options.params),
        queryFn: ()=>explainColumn(options.params),
        ...options?.query
    });
}
export function useExplainColumnSuspense<TData = {
    data: ColumnExplanationOut;
}>(options: {
    params: ExplainColumnParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: ColumnExplanationOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: explainColumnKey(options.params),
        queryFn: ()=>explainColumn(options.params),
        ...options?.query
    });
}
export interface ExplainColumnGraphParams {
    principal: string;
    column: string;
}
export const explainColumnGraph = async (params: ExplainColumnGraphParams, options?: RequestInit): Promise<{
    data: ChainGraphOut;
}> =>{
    const searchParams = new URLSearchParams();
    if (params.principal != null) searchParams.set("principal", String(params.principal));
    if (params.column != null) searchParams.set("column", String(params.column));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/explain-column-graph?${queryString}` : "/api/explain-column-graph";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const explainColumnGraphKey = (params?: ExplainColumnGraphParams)=>{
    return [
        "/api/explain-column-graph",
        params
    ] as const;
};
export function useExplainColumnGraph<TData = {
    data: ChainGraphOut;
}>(options: {
    params: ExplainColumnGraphParams;
    query?: Omit<UseQueryOptions<{
        data: ChainGraphOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: explainColumnGraphKey(options.params),
        queryFn: ()=>explainColumnGraph(options.params),
        ...options?.query
    });
}
export function useExplainColumnGraphSuspense<TData = {
    data: ChainGraphOut;
}>(options: {
    params: ExplainColumnGraphParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: ChainGraphOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: explainColumnGraphKey(options.params),
        queryFn: ()=>explainColumnGraph(options.params),
        ...options?.query
    });
}
export interface ExplainGraphParams {
    principal: string;
    table: string;
    include_column_masks?: boolean;
    include_row_filters?: boolean;
    include_grants?: boolean;
    focus_column?: string | null;
}
export const explainGraph = async (params: ExplainGraphParams, options?: RequestInit): Promise<{
    data: ChainGraphOut;
}> =>{
    const searchParams = new URLSearchParams();
    if (params.principal != null) searchParams.set("principal", String(params.principal));
    if (params.table != null) searchParams.set("table", String(params.table));
    if (params?.include_column_masks != null) searchParams.set("include_column_masks", String(params?.include_column_masks));
    if (params?.include_row_filters != null) searchParams.set("include_row_filters", String(params?.include_row_filters));
    if (params?.include_grants != null) searchParams.set("include_grants", String(params?.include_grants));
    if (params?.focus_column != null) searchParams.set("focus_column", String(params?.focus_column));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/explain-graph?${queryString}` : "/api/explain-graph";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const explainGraphKey = (params?: ExplainGraphParams)=>{
    return [
        "/api/explain-graph",
        params
    ] as const;
};
export function useExplainGraph<TData = {
    data: ChainGraphOut;
}>(options: {
    params: ExplainGraphParams;
    query?: Omit<UseQueryOptions<{
        data: ChainGraphOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: explainGraphKey(options.params),
        queryFn: ()=>explainGraph(options.params),
        ...options?.query
    });
}
export function useExplainGraphSuspense<TData = {
    data: ChainGraphOut;
}>(options: {
    params: ExplainGraphParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: ChainGraphOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: explainGraphKey(options.params),
        queryFn: ()=>explainGraph(options.params),
        ...options?.query
    });
}
export interface AccessGraphParams {
    principal: string;
}
export const accessGraph = async (params: AccessGraphParams, options?: RequestInit): Promise<{
    data: GraphOut;
}> =>{
    const searchParams = new URLSearchParams();
    if (params.principal != null) searchParams.set("principal", String(params.principal));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/graph?${queryString}` : "/api/graph";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const accessGraphKey = (params?: AccessGraphParams)=>{
    return [
        "/api/graph",
        params
    ] as const;
};
export function useAccessGraph<TData = {
    data: GraphOut;
}>(options: {
    params: AccessGraphParams;
    query?: Omit<UseQueryOptions<{
        data: GraphOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: accessGraphKey(options.params),
        queryFn: ()=>accessGraph(options.params),
        ...options?.query
    });
}
export function useAccessGraphSuspense<TData = {
    data: GraphOut;
}>(options: {
    params: AccessGraphParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: GraphOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: accessGraphKey(options.params),
        queryFn: ()=>accessGraph(options.params),
        ...options?.query
    });
}
export interface InverseAccessGraphParams {
    securable: string;
}
export const inverseAccessGraph = async (params: InverseAccessGraphParams, options?: RequestInit): Promise<{
    data: InverseGraphOut;
}> =>{
    const searchParams = new URLSearchParams();
    if (params.securable != null) searchParams.set("securable", String(params.securable));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/inverse-graph?${queryString}` : "/api/inverse-graph";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const inverseAccessGraphKey = (params?: InverseAccessGraphParams)=>{
    return [
        "/api/inverse-graph",
        params
    ] as const;
};
export function useInverseAccessGraph<TData = {
    data: InverseGraphOut;
}>(options: {
    params: InverseAccessGraphParams;
    query?: Omit<UseQueryOptions<{
        data: InverseGraphOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: inverseAccessGraphKey(options.params),
        queryFn: ()=>inverseAccessGraph(options.params),
        ...options?.query
    });
}
export function useInverseAccessGraphSuspense<TData = {
    data: InverseGraphOut;
}>(options: {
    params: InverseAccessGraphParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: InverseGraphOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: inverseAccessGraphKey(options.params),
        queryFn: ()=>inverseAccessGraph(options.params),
        ...options?.query
    });
}
export const meta = async (options?: RequestInit): Promise<{
    data: MetaOut;
}> =>{
    const res = await fetch("/api/meta", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const metaKey = ()=>{
    return [
        "/api/meta"
    ] as const;
};
export function useMeta<TData = {
    data: MetaOut;
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: MetaOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: metaKey(),
        queryFn: ()=>meta(),
        ...options?.query
    });
}
export function useMetaSuspense<TData = {
    data: MetaOut;
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: MetaOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: metaKey(),
        queryFn: ()=>meta(),
        ...options?.query
    });
}
export const listPrincipals = async (options?: RequestInit): Promise<{
    data: PrincipalOut[];
}> =>{
    const res = await fetch("/api/principals", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listPrincipalsKey = ()=>{
    return [
        "/api/principals"
    ] as const;
};
export function useListPrincipals<TData = {
    data: PrincipalOut[];
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: PrincipalOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listPrincipalsKey(),
        queryFn: ()=>listPrincipals(),
        ...options?.query
    });
}
export function useListPrincipalsSuspense<TData = {
    data: PrincipalOut[];
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: PrincipalOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listPrincipalsKey(),
        queryFn: ()=>listPrincipals(),
        ...options?.query
    });
}
export const refresh = async (options?: RequestInit): Promise<{
    data: MetaOut;
}> =>{
    const res = await fetch("/api/refresh", {
        ...options,
        method: "POST"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export function useRefresh(options?: {
    mutation?: UseMutationOptions<{
        data: MetaOut;
    }, ApiError, void>;
}) {
    return useMutation({
        mutationFn: ()=>refresh(),
        ...options?.mutation
    });
}
export const listTables = async (options?: RequestInit): Promise<{
    data: string[];
}> =>{
    const res = await fetch("/api/tables", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const listTablesKey = ()=>{
    return [
        "/api/tables"
    ] as const;
};
export function useListTables<TData = {
    data: string[];
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: string[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: listTablesKey(),
        queryFn: ()=>listTables(),
        ...options?.query
    });
}
export function useListTablesSuspense<TData = {
    data: string[];
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: string[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: listTablesKey(),
        queryFn: ()=>listTables(),
        ...options?.query
    });
}
export interface SecurableTreeParams {
    principal?: string | null;
}
export const securableTree = async (params?: SecurableTreeParams, options?: RequestInit): Promise<{
    data: TreeNodeOut[];
}> =>{
    const searchParams = new URLSearchParams();
    if (params?.principal != null) searchParams.set("principal", String(params?.principal));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/tree?${queryString}` : "/api/tree";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const securableTreeKey = (params?: SecurableTreeParams)=>{
    return [
        "/api/tree",
        params
    ] as const;
};
export function useSecurableTree<TData = {
    data: TreeNodeOut[];
}>(options?: {
    params?: SecurableTreeParams;
    query?: Omit<UseQueryOptions<{
        data: TreeNodeOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: securableTreeKey(options?.params),
        queryFn: ()=>securableTree(options?.params),
        ...options?.query
    });
}
export function useSecurableTreeSuspense<TData = {
    data: TreeNodeOut[];
}>(options?: {
    params?: SecurableTreeParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: TreeNodeOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: securableTreeKey(options?.params),
        queryFn: ()=>securableTree(options?.params),
        ...options?.query
    });
}
export const version = async (options?: RequestInit): Promise<{
    data: VersionOut;
}> =>{
    const res = await fetch("/api/version", {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const versionKey = ()=>{
    return [
        "/api/version"
    ] as const;
};
export function useVersion<TData = {
    data: VersionOut;
}>(options?: {
    query?: Omit<UseQueryOptions<{
        data: VersionOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: versionKey(),
        queryFn: ()=>version(),
        ...options?.query
    });
}
export function useVersionSuspense<TData = {
    data: VersionOut;
}>(options?: {
    query?: Omit<UseSuspenseQueryOptions<{
        data: VersionOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: versionKey(),
        queryFn: ()=>version(),
        ...options?.query
    });
}
export interface WhoCanSeeParams {
    column: string;
}
export const whoCanSee = async (params: WhoCanSeeParams, options?: RequestInit): Promise<{
    data: ColumnAccessRowOut[];
}> =>{
    const searchParams = new URLSearchParams();
    if (params.column != null) searchParams.set("column", String(params.column));
    const queryString = searchParams.toString();
    const url = queryString ? `/api/who-can-see?${queryString}` : "/api/who-can-see";
    const res = await fetch(url, {
        ...options,
        method: "GET"
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const whoCanSeeKey = (params?: WhoCanSeeParams)=>{
    return [
        "/api/who-can-see",
        params
    ] as const;
};
export function useWhoCanSee<TData = {
    data: ColumnAccessRowOut[];
}>(options: {
    params: WhoCanSeeParams;
    query?: Omit<UseQueryOptions<{
        data: ColumnAccessRowOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: whoCanSeeKey(options.params),
        queryFn: ()=>whoCanSee(options.params),
        ...options?.query
    });
}
export function useWhoCanSeeSuspense<TData = {
    data: ColumnAccessRowOut[];
}>(options: {
    params: WhoCanSeeParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: ColumnAccessRowOut[];
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: whoCanSeeKey(options.params),
        queryFn: ()=>whoCanSee(options.params),
        ...options?.query
    });
}
export interface WhoamiParams {
    "X-Forwarded-Host"?: string | null;
    "X-Forwarded-Preferred-Username"?: string | null;
    "X-Forwarded-User"?: string | null;
    "X-Forwarded-Email"?: string | null;
    "X-Request-Id"?: string | null;
    "X-Forwarded-Access-Token"?: string | null;
}
export const whoami = async (params?: WhoamiParams, options?: RequestInit): Promise<{
    data: WhoAmIOut;
}> =>{
    const res = await fetch("/api/whoami", {
        ...options,
        method: "GET",
        headers: {
            ...(params?.["X-Forwarded-Host"] != null && {
                "X-Forwarded-Host": params["X-Forwarded-Host"]
            }),
            ...(params?.["X-Forwarded-Preferred-Username"] != null && {
                "X-Forwarded-Preferred-Username": params["X-Forwarded-Preferred-Username"]
            }),
            ...(params?.["X-Forwarded-User"] != null && {
                "X-Forwarded-User": params["X-Forwarded-User"]
            }),
            ...(params?.["X-Forwarded-Email"] != null && {
                "X-Forwarded-Email": params["X-Forwarded-Email"]
            }),
            ...(params?.["X-Request-Id"] != null && {
                "X-Request-Id": params["X-Request-Id"]
            }),
            ...(params?.["X-Forwarded-Access-Token"] != null && {
                "X-Forwarded-Access-Token": params["X-Forwarded-Access-Token"]
            }),
            ...options?.headers
        }
    });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown;
        try {
            parsed = JSON.parse(body);
        } catch  {
            parsed = body;
        }
        throw new ApiError(res.status, res.statusText, parsed);
    }
    return {
        data: await res.json()
    };
};
export const whoamiKey = (params?: WhoamiParams)=>{
    return [
        "/api/whoami",
        params
    ] as const;
};
export function useWhoami<TData = {
    data: WhoAmIOut;
}>(options?: {
    params?: WhoamiParams;
    query?: Omit<UseQueryOptions<{
        data: WhoAmIOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useQuery({
        queryKey: whoamiKey(options?.params),
        queryFn: ()=>whoami(options?.params),
        ...options?.query
    });
}
export function useWhoamiSuspense<TData = {
    data: WhoAmIOut;
}>(options?: {
    params?: WhoamiParams;
    query?: Omit<UseSuspenseQueryOptions<{
        data: WhoAmIOut;
    }, ApiError, TData>, "queryKey" | "queryFn">;
}) {
    return useSuspenseQuery({
        queryKey: whoamiKey(options?.params),
        queryFn: ()=>whoami(options?.params),
        ...options?.query
    });
}
