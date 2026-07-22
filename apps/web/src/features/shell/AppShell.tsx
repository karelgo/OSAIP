// Studio frame: top bar over rail + content. The omnibar and inbox mount here so
// every studio screen shares them (§6.3).
import { Outlet } from "@tanstack/react-router";
import { useEffect } from "react";
import { Omnibar } from "../omnibar/Omnibar";
import { InboxDrawer } from "../notifications/InboxDrawer";
import { SseBridge } from "../notifications/SseBridge";
import { TopBar } from "./TopBar";
import { Rail } from "./Rail";
import { applyTheme, useShell } from "./theme";

export function AppShell() {
  const { theme, density, setOmnibarOpen } = useShell();

  useEffect(() => {
    applyTheme(theme, density);
  }, [theme, density]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOmnibarOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setOmnibarOpen]);

  return (
    <div className="flex h-screen flex-col bg-bg text-text">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Rail />
        <main className="min-w-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
      <Omnibar />
      <InboxDrawer />
      <SseBridge />
    </div>
  );
}
