import { ThemeProvider, useTheme } from "@/components/apx/theme-provider";
import { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import { Toaster } from "sonner";

function ThemedToaster() {
  const { theme } = useTheme();
  return <Toaster richColors theme={theme} />;
}

function RootError({ error, reset }: { error: unknown; reset: () => void }) {
  return (
    <main className="min-h-screen grid place-items-center p-6">
      <div role="alert" className="w-full max-w-lg rounded-md border p-6">
        <h1 className="text-lg font-semibold">
          ABAC Policy Explorer could not load
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {error instanceof Error ? error.message : String(error)}
        </p>
        <button
          type="button"
          className="mt-4 rounded-md border px-3 py-2 text-sm hover:bg-muted"
          onClick={reset}
        >
          Try again
        </button>
      </div>
    </main>
  );
}

export const Route = createRootRouteWithContext<{
  queryClient: QueryClient;
}>()({
  errorComponent: RootError,
  component: () => (
    <ThemeProvider defaultTheme="light" storageKey="apx-ui-theme">
      <Outlet />
      <ThemedToaster />
    </ThemeProvider>
  ),
});
