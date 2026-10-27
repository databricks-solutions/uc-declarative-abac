import { useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ModeToggle } from "@/components/apx/mode-toggle";
import { useMetaSuspense, type MetaOut } from "@/lib/api";
import { PrincipalProvider } from "./principal-context";
import { QueryBoundary } from "./query-boundary";
import { SkinProvider } from "./skin-context";
import { useViewerUrlState } from "./viewer-url-state";

/** The number of warnings the badge counts: the drift items plus the other
 * warnings, which the backend reports separately. */
function warningCount(metadata: MetaOut): number {
  return metadata.drift.length + metadata.warnings.length;
}

/** The warnings badge: opens a list in which each drift item links to the graph
 * of its grantee, focused on the securable whose expected privilege is missing,
 * so the policy -> securable path that diverged is highlighted. */
function WarningsMenu({ metadata }: { metadata: MetaOut }) {
  const [open, setOpen] = useState(false);
  const count = warningCount(metadata);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={`${count} warnings: show details`}
        data-warnings-toggle
      >
        <Badge variant="destructive" className="cursor-pointer text-[10px]">
          {count} {count === 1 ? "warning" : "warnings"}
        </Badge>
      </button>
      {open && (
        <div
          className="absolute left-0 top-full z-50 mt-2 w-[32rem] max-w-[90vw] space-y-3 rounded-md border bg-popover p-3 font-sans text-xs text-popover-foreground shadow-lg"
          data-warnings-panel
        >
          {metadata.drift.length > 0 && (
            <div className="space-y-1.5">
              <div className="font-semibold">
                Drift: declared in the config, not held in Unity Catalog
              </div>
              {metadata.drift.map((d) => (
                <Link
                  key={`${d.policy_id}|${d.principal}|${d.securable}|${d.privilege}`}
                  to="/"
                  search={{ p: d.principal, uNode: d.securable }}
                  onClick={() => setOpen(false)}
                  className="block rounded border border-transparent px-2 py-1 hover:border-border hover:bg-muted"
                  data-drift-link
                >
                  <span className="font-mono">{d.privilege}</span> on{" "}
                  <span className="font-mono">{d.securable}</span> for{" "}
                  <span className="font-mono">{d.principal}</span>
                  <span className="text-muted-foreground">
                    {" "}
                    (grant policy {d.policy_name}): show path
                  </span>
                </Link>
              ))}
            </div>
          )}
          {metadata.warnings.length > 0 && (
            <div className="space-y-1">
              <div className="font-semibold">Other warnings</div>
              {metadata.warnings.map((warning) => (
                <div key={warning} className="px-2 text-muted-foreground">
                  {warning}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RevisionBadge() {
  const { data } = useMetaSuspense({});
  const metadata = data.data;
  return (
    <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
      <Badge variant="outline" className="font-mono text-[10px]">
        rev {metadata.revision}
      </Badge>
      {metadata.tables} tables · {metadata.principals} principals ·{" "}
      {metadata.policies} policies
      {warningCount(metadata) > 0 && <WarningsMenu metadata={metadata} />}
    </div>
  );
}

function SourceNote() {
  const { data } = useMetaSuspense({});
  return (
    <>
      Answers reflect the <span className="font-medium">deployed state</span>{" "}
      dumped by uc-abac dump into{" "}
      <span className="font-mono">{data.data.source}</span>, including grants
      made outside the config. Ownership and admin roles are not modelled.
    </>
  );
}

export function ViewerPage({ children }: { children: ReactNode }) {
  const { search, update } = useViewerUrlState();

  return (
    <QueryBoundary
      fallback={
        <div className="space-y-4 p-8">
          <Skeleton className="h-10 w-96" />
          <Skeleton className="h-64 w-full" />
        </div>
      }
    >
      <SkinProvider>
        <PrincipalProvider
          selectedPrincipal={search.p}
          onPrincipalChange={(principal) =>
            void update({
              p: principal,
              uNode: undefined,
              uTarget: undefined,
              uSearch: undefined,
              uEffect: undefined,
              uEffectTable: undefined,
              uEffectColumn: undefined,
            })
          }
        >
          <div className="flex min-h-screen flex-col">
            <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-4 border-b bg-background/95 px-3 py-3 backdrop-blur sm:px-6">
              <div>
                <h1 className="text-lg font-semibold leading-tight">
                  <Link to="/" search={{ p: search.p }}>
                    ABAC Policy Explorer
                  </Link>
                </h1>
                <QueryBoundary
                  fallback={<Skeleton className="mt-1 h-4 w-64" />}
                >
                  <RevisionBadge />
                </QueryBoundary>
              </div>
              <div className="flex items-center gap-2">
                <ModeToggle />
              </div>
            </header>
            <main className="flex-1 px-3 py-4 sm:px-6">{children}</main>
            <footer className="border-t px-3 py-2 text-[11px] text-muted-foreground sm:px-6">
              <QueryBoundary fallback={null}>
                <SourceNote />
              </QueryBoundary>
            </footer>
          </div>
        </PrincipalProvider>
      </SkinProvider>
    </QueryBoundary>
  );
}
