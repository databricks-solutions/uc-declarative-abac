import { ExternalLink } from "lucide-react";
import type { ChainGroupOut, ChainNodeOut } from "@/lib/api";
import { useGithubLinker } from "./github-link";

/** Grouped chain detail — one deduplicated block per reason, mirroring the
 * anchor-model graph: a shared header (membership → tag → policy) with the
 * effects it produces underneath. Nodes with a config source deep-link to
 * GitHub at the deployed commit. */

const NODE_STYLE: Record<string, string> = {
  membership: "border-l-[#2a78d6] dark:border-l-[#63aaff]",
  tag: "border-l-[#1baf7a] dark:border-l-[#3cc8df]",
  policy: "border-l-[#4a3aa7] dark:border-l-[#9085e9]",
  grant: "border-l-[#008300] dark:border-l-[#57b95d]",
  effect: "border-l-[#b77900] dark:border-l-[#f2b84b]",
};

function NodeRow({
  node,
  href,
  compact = false,
}: {
  node: ChainNodeOut;
  href: string | null;
  compact?: boolean;
}) {
  return (
    <div
      className={`border-l-4 ${NODE_STYLE[node.kind] ?? "border-l-border"} bg-muted/40 rounded-r-md px-3 py-2 ${compact ? "ml-6" : ""}`}
      title={node.detail || undefined}
    >
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground w-16 shrink-0">
          {node.kind}
        </span>
        <span className="text-sm font-medium">{node.label}</span>
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground hover:text-foreground"
            title={`Open ${node.source} on GitHub`}
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      {node.detail && (
        <div className="text-xs text-muted-foreground mt-0.5 pl-[4.5rem]">
          {node.detail}
        </div>
      )}
      {node.source && (
        <div className="text-[11px] font-mono text-muted-foreground/80 mt-0.5 pl-[4.5rem]">
          {href ? (
            <a href={href} target="_blank" rel="noopener noreferrer" className="hover:underline">
              ↳ {node.source}
            </a>
          ) : (
            <>↳ {node.source}</>
          )}
        </div>
      )}
    </div>
  );
}

export function GroupedChainDetail({ groups }: { groups: ChainGroupOut[] }) {
  const linker = useGithubLinker();
  if (groups.length === 0) return null;
  return (
    <div className="space-y-4">
      <h4 className="text-sm font-medium">Chain detail</h4>
      {groups.map((g, i) => (
        <div key={i} className="space-y-1 rounded-md border p-2">
          <NodeRow node={g.membership} href={linker(g.membership.source)} />
          {g.tag && <NodeRow node={g.tag} href={linker(g.tag.source)} />}
          <NodeRow node={g.policy} href={linker(g.policy.source)} />
          {g.effects.map((e, j) => (
            <NodeRow key={j} node={e} href={linker(e.source)} compact />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Flat list fallback (used where grouped structure isn't available). */
export function FlatChainDetail({ chains }: { chains: ChainNodeOut[][] }) {
  const linker = useGithubLinker();
  if (chains.length === 0) return null;
  return (
    <div className="space-y-4">
      <h4 className="text-sm font-medium">Chain detail</h4>
      {chains.map((chain, i) => (
        <div key={i} className="space-y-1">
          {chain.map((node, j) => (
            <NodeRow key={j} node={node} href={linker(node.source)} />
          ))}
        </div>
      ))}
    </div>
  );
}
