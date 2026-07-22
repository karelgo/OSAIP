// Left rail (§6.2): grouped, collapsible to icons, fully keyboard-traversable.
import { Link, useParams } from "@tanstack/react-router";
import { Tooltip, TooltipContent, TooltipTrigger, cn } from "@osaip/ui";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { RAIL_GROUPS } from "./nav";
import { useShell } from "./theme";

export function Rail() {
  const collapsed = useShell((state) => state.railCollapsed);
  const toggleRail = useShell((state) => state.toggleRail);
  const { key } = useParams({ strict: false }) as { key?: string };
  const projectKey = key ?? "";

  return (
    <nav
      aria-label="Project navigation"
      data-testid="rail"
      className={cn(
        "flex h-full flex-col border-r border-border bg-surface transition-[width] duration-fast",
        collapsed ? "w-12" : "w-56",
      )}
    >
      <div className="flex-1 overflow-y-auto py-2">
        {RAIL_GROUPS.map((group, groupIndex) => (
          <div key={group.label ?? `group-${groupIndex}`} className="px-2 pb-2">
            {group.label && !collapsed && (
              <div className="px-2 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-faint">
                {group.label}
              </div>
            )}
            <ul>
              {group.items.map((item) => {
                const to =
                  item.path === "." ? `/p/${projectKey}` : `/p/${projectKey}/${item.path}`;
                const link = (
                  <Link
                    to={to}
                    data-rail-item={item.label}
                    className={cn(
                      "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted",
                      "hover:bg-bg-subtle hover:text-text",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                      "[&.active]:bg-accent-subtle [&.active]:text-text",
                    )}
                    activeOptions={{ exact: item.path === "." }}
                  >
                    <item.icon aria-hidden className="size-4 shrink-0" />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </Link>
                );
                return (
                  <li key={item.label}>
                    {collapsed ? (
                      <Tooltip>
                        <TooltipTrigger asChild>{link}</TooltipTrigger>
                        <TooltipContent side="right">{item.label}</TooltipContent>
                      </Tooltip>
                    ) : (
                      link
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={toggleRail}
        aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        className={cn(
          "m-2 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted",
          "hover:bg-bg-subtle hover:text-text",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        )}
      >
        {collapsed ? (
          <PanelLeftOpen aria-hidden className="size-4" />
        ) : (
          <>
            <PanelLeftClose aria-hidden className="size-4" />
            <span>Collapse</span>
          </>
        )}
      </button>
    </nav>
  );
}
