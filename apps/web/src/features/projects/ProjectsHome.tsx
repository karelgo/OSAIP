// Projects home (/): list + non-modal create side-panel (§6.3(2): modals are for
// destructive confirmation only — creation opens an inspector-style panel).
import {
  Badge,
  Button,
  EmptyState,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@osaip/ui";
import { listProjectsOptions } from "@osaip/api-client";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { AlertTriangle, FolderKanban, Plus } from "lucide-react";
import { CreateProjectPanel } from "./CreateProjectPanel";

export function ProjectsHome() {
  const navigate = useNavigate();
  const search = useSearch({ from: "/_authed/_shell/" }) as { new?: boolean };
  const projects = useQuery(listProjectsOptions());
  const panelOpen = search.new === true;

  function setPanelOpen(open: boolean) {
    void navigate({ to: "/", search: open ? { new: true } : {} });
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl gap-6 p-6">
      <section className="min-w-0 flex-1">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Projects</h1>
            <p className="text-sm text-muted">Workspaces with members, data, and agents.</p>
          </div>
          <Button data-testid="new-project" onClick={() => setPanelOpen(true)}>
            <Plus aria-hidden className="size-4" /> New project
          </Button>
        </div>

        <div className="mt-6">
          {projects.isLoading && (
            <div className="space-y-2" data-testid="projects-loading">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          )}

          {projects.isError && (
            <EmptyState
              data-testid="projects-error"
              icon={<AlertTriangle aria-hidden className="size-8" />}
              title="Couldn't load projects"
              description="The API did not respond. Check your connection, then retry."
            >
              <Button variant="secondary" onClick={() => projects.refetch()}>
                Retry
              </Button>
            </EmptyState>
          )}

          {projects.isSuccess && projects.data.items.length === 0 && (
            <EmptyState
              icon={<FolderKanban aria-hidden className="size-8" />}
              title="No projects yet"
              description="A project is where data, flows, and agents live. Create the first one to get going."
            >
              <Button onClick={() => setPanelOpen(true)}>
                <Plus aria-hidden className="size-4" /> Create a project
              </Button>
            </EmptyState>
          )}

          {projects.isSuccess && projects.data.items.length > 0 && (
            <Table data-testid="projects-table">
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Key</TH>
                  <TH>Your role</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                {projects.data.items.map((project) => (
                  <TR key={project.key}>
                    <TD>
                      <Link
                        to="/p/$key"
                        params={{ key: project.key }}
                        className="font-medium text-text underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      >
                        {project.name}
                      </Link>
                    </TD>
                    <TD className="font-mono text-xs text-muted">{project.key}</TD>
                    <TD>
                      <Badge variant="neutral">{project.role}</Badge>
                    </TD>
                    <TD>
                      <Badge variant={project.status === "active" ? "success" : "neutral"}>
                        {project.status}
                      </Badge>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </div>
      </section>

      {panelOpen && <CreateProjectPanel onClose={() => setPanelOpen(false)} />}
    </div>
  );
}
