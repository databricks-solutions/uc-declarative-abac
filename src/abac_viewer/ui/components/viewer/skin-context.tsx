import { createContext, useContext, useEffect, type ReactNode } from "react";

export type Skin = "databricks";

type SkinContextValue = { skin: Skin };

const SkinContext = createContext<SkinContextValue | null>(null);
const STORAGE_KEY = "abac-viewer-skin";
const DATABRICKS_SKIN: SkinContextValue = { skin: "databricks" };

export function SkinProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    localStorage.removeItem(STORAGE_KEY);
    document.documentElement.setAttribute("data-skin", "databricks");
  }, []);
  return (
    <SkinContext.Provider value={DATABRICKS_SKIN}>
      {children}
    </SkinContext.Provider>
  );
}

export function useSkin(): SkinContextValue {
  const ctx = useContext(SkinContext);
  if (!ctx) throw new Error("useSkin outside SkinProvider");
  return ctx;
}
