import { useEffect, useState } from "react";
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { Period } from "@/components/charts";

interface UIState {
  period: Period;
  setPeriod: (period: Period) => void;
}

const useUIStoreBase = create<UIState>()(
  persist(
    (set) => ({
      period: "1Y",
      setPeriod: (period) => set({ period }),
    }),
    {
      name: "ui-preferences",
      storage: createJSONStorage(() => sessionStorage),
      skipHydration: true,
    }
  )
);

/**
 * Hook that safely accesses the UI store after hydration.
 * Returns the default period during SSR and initial render to avoid hydration mismatches.
 */
export function useUIStore() {
  const [isHydrated, setIsHydrated] = useState(false);
  const store = useUIStoreBase();

  useEffect(() => {
    useUIStoreBase.persist.rehydrate();
    setIsHydrated(true);
  }, []);

  // Return default value during SSR and first render to match server
  if (!isHydrated) {
    return {
      period: "1Y" as Period,
      setPeriod: store.setPeriod,
    };
  }

  return store;
}
