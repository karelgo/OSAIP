// Consumer portal (/hub): chat-first, zero studio chrome, mobile-friendly (§6.1).
// Real agent chat arrives in Phase 7 — this stub is still a designed, usable page.
import { Button, EmptyState } from "@osaip/ui";
import { MessageSquare } from "lucide-react";
import { useEffect } from "react";
import { applyTheme, useShell } from "../shell/theme";

export function HubPage() {
  const { theme, density } = useShell();
  useEffect(() => {
    applyTheme(theme, density);
  }, [theme, density]);

  return (
    <main
      data-testid="hub-page"
      className="flex min-h-screen flex-col bg-bg text-text"
    >
      <header className="flex h-14 items-center justify-between border-b border-border px-4">
        <span className="font-semibold tracking-tight">OSAIP Hub</span>
        <a
          href="/"
          className="text-sm text-muted underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Open Studio
        </a>
      </header>
      <div className="flex flex-1 items-center justify-center p-6">
        <EmptyState
          icon={<MessageSquare aria-hidden className="size-8" />}
          title="Your agents will live here"
          description="From phase 7, the Hub is where you chat with approved agents and Answers apps — no studio required. Conversations with AI systems are always labeled as such."
        >
          <Button variant="secondary" onClick={() => window.location.assign("/")}>
            Explore the Studio
          </Button>
        </EmptyState>
      </div>
    </main>
  );
}
