// Job detail (/p/$key/jobs/$jobId): the same step timeline + live log tail the run
// drawer shows, rendered inline (§6.3(4)).
import { Button } from "@osaip/ui";
import { getProjectOptions } from "@osaip/api-client";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { RunContent } from "../flow/RunDrawer";

const ROUTE_ID = "/_authed/_shell/p/$key/jobs/$jobId";

export function JobPage() {
  const { key, jobId } = useParams({ from: ROUTE_ID });
  const project = useQuery(getProjectOptions({ path: { key } }));
  const canEdit = project.data?.capabilities.can_edit ?? false;

  return (
    <div className="mx-auto max-w-5xl p-6" data-testid="job-page">
      <Button variant="ghost" size="sm" asChild className="mb-3">
        <Link to="/p/$key/jobs" params={{ key }}>
          <ArrowLeft aria-hidden className="size-4" /> All jobs
        </Link>
      </Button>
      <h1 className="mb-4 text-xl font-semibold tracking-tight">
        Run <span className="font-mono text-base text-muted">{jobId.slice(0, 8)}</span>
      </h1>
      <RunContent projectKey={key} jobId={jobId} canEdit={canEdit} />
    </div>
  );
}
