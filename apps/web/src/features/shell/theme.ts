// Shell-local UI state (§6.5: Zustand for local state). Theme/density mirror the
// server-side prefs (/me/prefs) once loaded; localStorage keeps the last value so
// the first paint after reload doesn't flash.
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "system" | "light" | "dark";
export type Density = "comfortable" | "compact";

interface ShellState {
  theme: Theme;
  density: Density;
  railCollapsed: boolean;
  omnibarOpen: boolean;
  inboxOpen: boolean;
  setTheme: (theme: Theme) => void;
  setDensity: (density: Density) => void;
  toggleRail: () => void;
  setOmnibarOpen: (open: boolean) => void;
  setInboxOpen: (open: boolean) => void;
}

export const useShell = create<ShellState>()(
  persist(
    (set) => ({
      theme: "system",
      density: "comfortable",
      railCollapsed: false,
      omnibarOpen: false,
      inboxOpen: false,
      setTheme: (theme) => set({ theme }),
      setDensity: (density) => set({ density }),
      toggleRail: () => set((state) => ({ railCollapsed: !state.railCollapsed })),
      setOmnibarOpen: (omnibarOpen) => set({ omnibarOpen }),
      setInboxOpen: (inboxOpen) => set({ inboxOpen }),
    }),
    {
      name: "osaip-shell",
      partialize: ({ theme, density, railCollapsed }) => ({ theme, density, railCollapsed }),
    },
  ),
);

export function applyTheme(theme: Theme, density: Density) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.dataset.density = density;
}
