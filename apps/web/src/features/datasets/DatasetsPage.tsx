// Datasets list (/p/$key/datasets): the phase-1 data surface. Rows are links,
// creation happens in non-modal side panels (§6.3(2)) — upload or register.
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
import { getProjectOptions, listDatasetsOptions } from "@osaip/api-client";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { AlertTriangle, Cable, Database, Upload } from "lucide-react";
import { ClassificationBadges, formatRowCount } from "./lib";
import { RegisterPanel } from "./RegisterPanel";
import { UploadPanel } from "./UploadPanel";

export function DatasetsPage() {
  const { key } = useParams({ from: "/_authed/_shell/p/$key/datasets" });
  const search = useSearch({ from: "/_authed/_shell/p/$key/datasets" });
  const navigate = useNavigate();
  const project = useQuery(getProjectOptions({ path: { key } }));
  const datasets = useQuery(listDatasetsOptions({ path: { key } }));

  const canEdit = project.data?.capabilities.can_edit ?? false;
  const panel = search.panel;

  function setPanel(next: "upload" | "register" | undefined) {
    void navigate({
      to: "/p/$key/datasets",
      params: { key },
      search: next ? { panel: next } : {},
    });
  }

  const items = datasets.data?.items ?? [];

  return (
    <div className="mx-auto flex h-full max-w-6xl items-start gap-6 p-6">
      <section className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Datasets</h1>
            <p className="text-sm text-muted">
              Typed, labeled data — uploaded files and registered source tables.
            </p>
          </div>
          {canEdit && (
            <div className="flex gap-2">
              <Button
                variant="secondary"
                data-testid="datasets-register"
                onClick={() => setPanel("register")}
              >
                <Cable aria-hidden className="size-4" /> Register from connection
              </Button>
              <Button data-testid="datasets-upload" onClick={() => setPanel("upload")}>
                <Upload aria-hidden className="size-4" /> Upload file
              </Button>
            </div>
          )}
        </div>

        <div className="mt-6">
          {datasets.isLoading && (
            <div className="space-y-2" data-testid="datasets-loading">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          )}

          {datasets.isError && (
            <EmptyState
              data-testid="datasets-error"
              icon={<AlertTriangle aria-hidden className="size-8" />}
              title="Couldn't load datasets"
              description="The API did not respond. Check your connection, then retry."
            >
              <Button variant="secondary" onClick={() => datasets.refetch()}>
                Retry
              </Button>
            </EmptyState>
          )}

          {datasets.isSuccess && items.length === 0 && (
            <EmptyState
              icon={<Database aria-hidden className="size-8" />}
              title="No datasets yet"
              description="Upload a CSV, Parquet, or Excel file — or register a table from a connection — to get typed, profiled data into this project."
            >
              {canEdit && (
                <Button onClick={() => setPanel("upload")}>
                  <Upload aria-hidden className="size-4" /> Upload file
                </Button>
              )}
            </EmptyState>
          )}

          {datasets.isSuccess && items.length > 0 && (
            <Table data-testid="datasets-table">
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Kind</TH>
                  <TH>Classification</TH>
                  <TH numeric>Rows</TH>
                  <TH>Updated</TH>
                </TR>
              </THead>
              <TBody>
                {items.map((dataset) => (
                  <TR
                    key={dataset.name}
                    data-testid="dataset-row"
                    className="cursor-pointer"
                    onClick={() =>
                      void navigate({
                        to: "/p/$key/datasets/$datasetName",
                        params: { key, datasetName: dataset.name },
                      })
                    }
                  >
                    <TD>
                      <Link
                        to="/p/$key/datasets/$datasetName"
                        params={{ key, datasetName: dataset.name }}
                        className="font-medium text-fg underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {dataset.name}
                      </Link>
                    </TD>
                    <TD>
                      <Badge variant="neutral">{dataset.kind}</Badge>
                    </TD>
                    <TD>
                      <ClassificationBadges
                        classification={dataset.classification}
                        bbnLevel={dataset.bbn_level}
                        confidentiality={dataset.confidentiality}
                      />
                    </TD>
                    <TD numeric className="tabular-nums">
                      {formatRowCount(dataset.row_count, dataset.row_count_kind)}
                    </TD>
                    <TD className="whitespace-nowrap text-muted">
                      {new Date(dataset.updated_at).toLocaleString()}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </div>
      </section>

      {panel === "upload" && canEdit && (
        <UploadPanel projectKey={key} onClose={() => setPanel(undefined)} />
      )}
      {panel === "register" && canEdit && (
        <RegisterPanel projectKey={key} onClose={() => setPanel(undefined)} />
      )}
    </div>
  );
}
