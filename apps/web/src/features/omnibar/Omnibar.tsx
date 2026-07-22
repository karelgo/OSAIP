// ⌘K omnibar (§6.3(5)): hybrid object search (server) + action registry (client).
// Unresolved input will fall through to Copilot in Phase 7.
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@osaip/ui";
import { searchOptions } from "@osaip/api-client";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import { Boxes, Database, FolderKanban, Plus, SunMoon } from "lucide-react";
import { useState } from "react";
import { useShell } from "../shell/theme";

const KIND_ICONS: Record<string, typeof Database> = {
  project: FolderKanban,
  dataset: Database,
};

interface Action {
  id: string;
  label: string;
  icon: typeof Database;
  run: () => void;
  keywords?: string;
}

export function Omnibar() {
  const navigate = useNavigate();
  const { omnibarOpen, setOmnibarOpen, setTheme, theme } = useShell();
  const { key: projectKey } = useParams({ strict: false }) as { key?: string };
  const [query, setQuery] = useState("");

  function handleOpenChange(open: boolean) {
    setOmnibarOpen(open);
    if (!open) setQuery("");
  }

  const results = useQuery({
    ...searchOptions({ query: { q: query } }),
    enabled: omnibarOpen && query.trim().length > 0,
    staleTime: 5_000,
    placeholderData: (previous) => previous,
  });

  // Action registry skeleton (§7 Phase 0) — modules register more actions later.
  const actions: Action[] = [
    {
      id: "new-project",
      label: "New project",
      icon: Plus,
      keywords: "create project",
      run: () => navigate({ to: "/", search: { new: true } }),
    },
    {
      id: "toggle-theme",
      label: `Switch to ${theme === "dark" ? "light" : "dark"} theme`,
      icon: SunMoon,
      keywords: "dark light theme mode",
      run: () => setTheme(theme === "dark" ? "light" : "dark"),
    },
    {
      id: "go-hub",
      label: "Open Hub",
      icon: Boxes,
      keywords: "consumer portal chat",
      run: () => navigate({ to: "/hub" }),
    },
  ];

  const items = results.data?.items ?? [];

  return (
    <CommandDialog
      open={omnibarOpen}
      onOpenChange={handleOpenChange}
      title="Search and commands"
      shouldFilter={query.trim().length > 0 ? false : true}
    >
      <CommandInput
        placeholder="Search objects or type a command…"
        value={query}
        onValueChange={setQuery}
        data-testid="omnibar-input"
      />
      <CommandList data-testid="omnibar-results">
        <CommandEmpty>
          {query ? "Nothing found. Copilot fallback arrives in phase 7." : "Type to search."}
        </CommandEmpty>
        {items.length > 0 && (
          <CommandGroup heading="Objects">
            {items.map((item) => {
              const Icon = KIND_ICONS[item.kind] ?? Boxes;
              return (
                <CommandItem
                  key={`${item.kind}:${item.url_path}`}
                  value={`${item.kind}:${item.name}:${item.url_path}`}
                  onSelect={() => {
                    setOmnibarOpen(false);
                    navigate({ to: item.url_path });
                  }}
                >
                  <Icon aria-hidden className="size-4" />
                  <span className="truncate">{item.name}</span>
                  <span className="ml-auto text-xs text-faint">
                    {item.project_key ? `${item.project_key} · ` : ""}
                    {item.kind}
                  </span>
                </CommandItem>
              );
            })}
          </CommandGroup>
        )}
        <CommandGroup heading="Actions">
          {actions.map((action) => (
            <CommandItem
              key={action.id}
              value={`${action.label} ${action.keywords ?? ""}`}
              onSelect={() => {
                setOmnibarOpen(false);
                action.run();
              }}
            >
              <action.icon aria-hidden className="size-4" />
              {action.label}
            </CommandItem>
          ))}
        </CommandGroup>
        {projectKey && (
          <CommandGroup heading="Current project">
            <CommandItem
              value={`open project ${projectKey}`}
              onSelect={() => {
                setOmnibarOpen(false);
                navigate({ to: "/p/$key", params: { key: projectKey } });
              }}
            >
              <FolderKanban aria-hidden className="size-4" />
              Go to project home
            </CommandItem>
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
