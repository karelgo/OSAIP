// Top bar (§6.2): project switcher (recents + search) · ⌘K trigger · run bell ·
// approvals inbox · Copilot toggle · user menu. Bell/approvals/copilot are visible,
// disabled affordances until their phases ship — never hidden-broken buttons.
import { useNavigate, useParams } from "@tanstack/react-router";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Kbd,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@osaip/ui";
import { listNotificationsOptions, listProjectsOptions, logout } from "@osaip/api-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type * as React from "react";
import {
  Bell,
  Check,
  ChevronsUpDown,
  Inbox,
  LogOut,
  Monitor,
  Moon,
  Search,
  Sparkles,
  Sun,
} from "lucide-react";
import { useMe } from "../auth/api";
import { type Theme, useShell } from "./theme";

function DisabledIconButton({
  label,
  phase,
  children,
}: {
  label: string;
  phase: number;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <Button variant="ghost" size="sm" disabled aria-label={`${label} (arrives in phase ${phase})`}>
            {children}
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {label} arrives in phase {phase}
      </TooltipContent>
    </Tooltip>
  );
}

export function TopBar() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { key } = useParams({ strict: false }) as { key?: string };
  const me = useMe();
  const projects = useQuery({ ...listProjectsOptions(), staleTime: 30_000 });
  const { theme, setTheme, setOmnibarOpen, setInboxOpen } = useShell();

  const projectItems = projects.data?.items ?? [];
  const current = projectItems.find((item) => item.key === key);

  async function handleLogout() {
    const response = await logout({ throwOnError: true });
    queryClient.clear();
    const url = (response.data as { logout_url?: string | null }).logout_url;
    window.location.assign(url ?? "/login");
  }

  const themeIcons: Record<Theme, typeof Sun> = { light: Sun, dark: Moon, system: Monitor };

  return (
    <header
      data-testid="topbar"
      className="flex h-12 items-center gap-2 border-b border-border bg-surface px-3"
    >
      <a href="/" className="flex items-center gap-2 rounded-md px-1 font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        OSAIP
      </a>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="secondary" size="sm" data-testid="project-switcher" className="min-w-40 justify-between">
            <span className="truncate">{current ? current.name : "Choose a project"}</span>
            <ChevronsUpDown aria-hidden className="size-3.5 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          <DropdownMenuLabel>Projects</DropdownMenuLabel>
          {projectItems.slice(0, 8).map((project) => (
            <DropdownMenuItem
              key={project.key}
              onSelect={() => navigate({ to: "/p/$key", params: { key: project.key } })}
            >
              <span className="truncate">{project.name}</span>
              {project.key === key && <Check aria-hidden className="ml-auto size-4" />}
            </DropdownMenuItem>
          ))}
          {projectItems.length === 0 && (
            <DropdownMenuItem onSelect={() => navigate({ to: "/" })}>
              No projects yet — create one
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setOmnibarOpen(true)}>
            <Search aria-hidden className="size-4" />
            Search everything
            <Kbd className="ml-auto">⌘K</Kbd>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => navigate({ to: "/" })}>
            All projects
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Button
        variant="secondary"
        size="sm"
        data-testid="omnibar-trigger"
        className="ml-2 w-64 justify-between text-muted"
        onClick={() => setOmnibarOpen(true)}
      >
        <span className="flex items-center gap-2">
          <Search aria-hidden className="size-3.5" />
          Search or run a command
        </span>
        <Kbd>⌘K</Kbd>
      </Button>

      <div className="ml-auto flex items-center gap-1">
        <DisabledIconButton label="Runs" phase={2}>
          <Bell aria-hidden className="size-4" />
        </DisabledIconButton>
        <DisabledIconButton label="Approvals" phase={6}>
          <Check aria-hidden className="size-4" />
        </DisabledIconButton>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Notifications"
              data-testid="inbox-button"
              onClick={() => setInboxOpen(true)}
            >
              <Inbox aria-hidden className="size-4" />
              <UnreadBadge />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Notifications</TooltipContent>
        </Tooltip>
        <DisabledIconButton label="Copilot" phase={7}>
          <Sparkles aria-hidden className="size-4" />
        </DisabledIconButton>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" data-testid="user-menu" aria-label="User menu">
              <span className="flex size-6 items-center justify-center rounded-full bg-accent-subtle text-xs font-medium">
                {(me.data?.display_name ?? "?").slice(0, 1).toUpperCase()}
              </span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="truncate">{me.data?.email}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {(["light", "dark", "system"] as const).map((option) => {
              const Icon = themeIcons[option];
              return (
                <DropdownMenuItem key={option} onSelect={() => setTheme(option)} data-testid={`theme-${option}`}>
                  <Icon aria-hidden className="size-4" />
                  <span className="capitalize">{option} theme</span>
                  {theme === option && <Check aria-hidden className="ml-auto size-4" />}
                </DropdownMenuItem>
              );
            })}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={handleLogout} data-testid="logout">
              <LogOut aria-hidden className="size-4" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

function UnreadBadge() {
  const { data } = useQuery({
    ...listNotificationsOptions(),
    staleTime: 15_000,
  });
  const unread = data?.unread_count ?? 0;
  if (unread === 0) return null;
  return (
    <Badge variant="accent" data-testid="unread-badge" className="ml-1 px-1.5 py-0 text-[10px]">
      {unread > 99 ? "99+" : unread}
    </Badge>
  );
}
