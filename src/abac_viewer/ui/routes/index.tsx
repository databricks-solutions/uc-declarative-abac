import { createFileRoute } from "@tanstack/react-router";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryBoundary } from "@/components/viewer/query-boundary";
import { UnifiedExplorer } from "@/components/viewer/unified-explorer";
import { ViewerPage } from "@/components/viewer/viewer-page";
import { validateViewerSearch } from "@/components/viewer/viewer-url-state";

export const Route = createFileRoute("/")({
  validateSearch: validateViewerSearch,
  component: Index,
});

function Index() {
  return (
    <ViewerPage>
      <QueryBoundary fallback={<Skeleton className="h-[36rem] w-full" />}>
        <UnifiedExplorer />
      </QueryBoundary>
    </ViewerPage>
  );
}
