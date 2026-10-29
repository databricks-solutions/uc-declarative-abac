import { createContext, useContext, type ReactNode } from "react";
import { KeyRound, User, Users } from "lucide-react";
import { useListPrincipalsSuspense } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type PrincipalContextValue = {
  principal: string;
  setPrincipal: (p: string) => void;
};

const PrincipalContext = createContext<PrincipalContextValue | null>(null);
export const ALL_PRINCIPALS = "__all__";

/** The principal shown when the URL names none: the first user or service
 * principal (principals are listed before groups, sorted), else the first one. */
function defaultPrincipalOf(principals: { name: string; kind: string }[]): string {
  return (
    principals.find((principal) => principal.kind !== "group")?.name ??
    principals[0]?.name ??
    ALL_PRINCIPALS
  );
}

/** Selected principal for every view. Unknown URL values are discarded so
 * only config-declared principals can be explored. */
export function PrincipalProvider({
  children,
  selectedPrincipal,
  onPrincipalChange,
}: {
  children: ReactNode;
  selectedPrincipal?: string;
  onPrincipalChange: (principal: string | undefined) => void;
}) {
  const { data } = useListPrincipalsSuspense({});
  const knownPrincipals = new Set(data.data.map((principal) => principal.name));
  const defaultPrincipal = defaultPrincipalOf(data.data);
  const principal =
    selectedPrincipal === ALL_PRINCIPALS ||
    (selectedPrincipal !== undefined && knownPrincipals.has(selectedPrincipal))
      ? selectedPrincipal
      : defaultPrincipal;
  return (
    <PrincipalContext.Provider
      value={{
        principal,
        setPrincipal: (p) =>
          onPrincipalChange(p === defaultPrincipal ? undefined : p),
      }}
    >
      {children}
    </PrincipalContext.Provider>
  );
}

export function usePrincipal(): PrincipalContextValue {
  const ctx = useContext(PrincipalContext);
  if (!ctx) throw new Error("usePrincipal outside PrincipalProvider");
  return ctx;
}

/** Shared principal picker containing only config-declared principals. */
export function PrincipalSelect({
  className,
  includeAll = false,
}: {
  className?: string;
  includeAll?: boolean;
}) {
  const { principal, setPrincipal } = usePrincipal();
  const { data } = useListPrincipalsSuspense({});
  const options = data.data
    .filter((p) => p.name !== "anonymous")
    .map((p) => ({ name: p.name, kind: p.kind }));
  return (
    <Select value={principal} onValueChange={setPrincipal}>
      <SelectTrigger className={className ?? "w-full font-mono text-xs sm:w-72"}>
        <SelectValue placeholder="principal…" />
      </SelectTrigger>
      <SelectContent>
        {includeAll && (
          <SelectItem value={ALL_PRINCIPALS} className="font-mono text-xs">
            <span className="flex items-center gap-2">
              <Users className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
              All
            </span>
          </SelectItem>
        )}
        {options.map((p) => {
          const Icon =
            p.kind === "group"
              ? Users
              : p.kind === "service_principal"
                ? KeyRound
                : User;
          return (
            <SelectItem key={p.name} value={p.name} className="font-mono text-xs">
              <span className="flex items-center gap-2">
                <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                {p.name}
              </span>
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}
