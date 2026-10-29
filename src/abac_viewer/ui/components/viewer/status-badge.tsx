import { Badge } from "@/components/ui/badge";
import { Ban, CircleCheck, Eye, EyeOff, ListFilter } from "lucide-react";

/** Verdict / mask state badges. Status colors are reserved for state and every
 * badge carries its label text — color is never the only signal. */

const STATUS: Record<string, { label: string; className: string }> = {
  full: {
    label: "READS UNMASKED",
    className:
      "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200 border-emerald-300 dark:border-emerald-800",
  },
  partial: {
    label: "MASKED",
    className:
      "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200 border-amber-300 dark:border-amber-800",
  },
  filtered: {
    label: "ROWS FILTERED",
    className:
      "bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-200 border-orange-300 dark:border-orange-800",
  },
  no_access: {
    label: "NO ACCESS",
    className: "bg-muted text-muted-foreground border-border",
  },
};

export function StatusBadge({
  status,
  compact = false,
}: {
  status: string;
  compact?: boolean;
}) {
  const s = STATUS[status] ?? STATUS.no_access;
  if (compact) {
    const Icon =
      status === "full"
        ? CircleCheck
        : status === "partial"
          ? EyeOff
          : status === "filtered"
            ? ListFilter
            : Ban;
    return (
      <Badge
        variant="outline"
        title={s.label}
        className={`size-6 justify-center p-0 ${s.className}`}
      >
        <Icon className="size-3" aria-hidden="true" />
        <span className="sr-only">{s.label}</span>
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className={`font-mono text-[11px] ${s.className}`}>
      {s.label}
    </Badge>
  );
}

export function AccessBadge({ canRead }: { canRead: boolean }) {
  return (
    <Badge
      variant="outline"
      className={
        canRead
          ? "font-mono text-[11px] bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200 border-emerald-300 dark:border-emerald-800"
          : "font-mono text-[11px] bg-muted text-muted-foreground border-border"
      }
    >
      {canRead ? "CAN READ" : "NO ACCESS"}
    </Badge>
  );
}

export function MaskBadge({
  masked,
  targeted = false,
  compact = false,
}: {
  masked: boolean;
  targeted?: boolean;
  compact?: boolean;
}) {
  if (compact) {
    const Icon = masked || targeted ? EyeOff : Eye;
    const label = masked
      ? "MASKED"
      : targeted
        ? "MASK POLICY (NOT APPLIED)"
        : "UNMASKED";
    return (
      <Badge
        variant="outline"
        className={`size-6 justify-center p-0 ${
          masked
            ? "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200 border-amber-300 dark:border-amber-800"
            : targeted
              ? "bg-muted text-muted-foreground border-border"
            : "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200 border-emerald-300 dark:border-emerald-800"
        }`}
        title={label}
      >
        <Icon className="size-3" aria-hidden="true" />
        <span className="sr-only">{label}</span>
      </Badge>
    );
  }
  return masked ? (
    <Badge
      variant="outline"
      className="font-mono text-[11px] bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200 border-amber-300 dark:border-amber-800"
    >
      MASKED
    </Badge>
  ) : targeted ? (
    <Badge
      variant="outline"
      className="gap-1 font-mono text-[11px] bg-muted text-muted-foreground border-border"
    >
      <EyeOff className="size-3" aria-hidden="true" />
      MASK POLICY
    </Badge>
  ) : (
    <Badge
      variant="outline"
      className="font-mono text-[11px] bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200 border-emerald-300 dark:border-emerald-800"
    >
      UNMASKED
    </Badge>
  );
}

export function FilterBadge({
  filtered,
  targeted = false,
  compact = false,
}: {
  filtered: boolean;
  targeted?: boolean;
  compact?: boolean;
}) {
  if (compact) {
    const Icon = filtered || targeted ? ListFilter : CircleCheck;
    const label = filtered
      ? "ROWS FILTERED"
      : targeted
        ? "ROW FILTER POLICY (NOT APPLIED)"
        : "UNFILTERED";
    return (
      <Badge
        variant="outline"
        className={`size-6 justify-center p-0 ${
          filtered
            ? "bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-200 border-orange-300 dark:border-orange-800"
            : targeted
              ? "bg-muted text-muted-foreground border-border"
            : "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200 border-emerald-300 dark:border-emerald-800"
        }`}
        title={label}
      >
        <Icon className="size-3" aria-hidden="true" />
        <span className="sr-only">{label}</span>
      </Badge>
    );
  }
  return filtered ? (
    <Badge
      variant="outline"
      className="gap-1 font-mono text-[11px] bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-200 border-orange-300 dark:border-orange-800"
    >
      <ListFilter className="size-3" aria-hidden="true" />
      FILTERED
    </Badge>
  ) : targeted ? (
    <Badge
      variant="outline"
      className="gap-1 font-mono text-[11px] bg-muted text-muted-foreground border-border"
    >
      <ListFilter className="size-3" aria-hidden="true" />
      FILTER POLICY
    </Badge>
  ) : (
    <Badge
      variant="outline"
      className="gap-1 font-mono text-[11px] bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200 border-emerald-300 dark:border-emerald-800"
    >
      <CircleCheck className="size-3" aria-hidden="true" />
      UNFILTERED
    </Badge>
  );
}
