// Resolve the shell theme ("system" | "light" | "dark") to a concrete mode for the
// canvas (xyflow colorMode) and Monaco. Mirrors the token system: "system" follows
// prefers-color-scheme.
import { useSyncExternalStore } from "react";
import { useShell } from "../shell/theme";

function subscribe(callback: () => void): () => void {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function useColorMode(): "light" | "dark" {
  const theme = useShell((state) => state.theme);
  const prefersDark = useSyncExternalStore(subscribe, systemPrefersDark, () => false);
  if (theme === "dark") return "dark";
  if (theme === "light") return "light";
  return prefersDark ? "dark" : "light";
}
