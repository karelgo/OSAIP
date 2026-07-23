// Upload flow (§6.3(3) LOCKED, preview-first): pick a file → server infers a typed
// schema + preview → confirm metadata → create the dataset. Non-modal side panel
// per §6.3(2) — the CreateProjectPanel pattern.
import { Button, Field, Spinner, toast } from "@osaip/ui";
import {
  createDataset,
  createUpload,
  listDatasetsQueryKey,
  type UploadOut,
} from "@osaip/api-client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { asProblem, problemToast } from "../../lib/problem";
import { DatasetMetaFields } from "./MetaFields";
import { SchemaPreview } from "./SchemaPreview";
import { datasetMetaSchema, parsePurposeCodes, slugifyName, toDatasetMeta, type DatasetMetaValues } from "./lib";

// Uploads have no connection to inherit from — CP-2 fields are required here.
const schema = datasetMetaSchema.superRefine((values, ctx) => {
  if (values.legal_basis.trim() === "") {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["legal_basis"],
      message: "State the legal basis for holding this data (CP-2)",
    });
  }
  if (parsePurposeCodes(values.purpose_codes).length === 0) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["purpose_codes"],
      message: "Give at least one purpose code (CP-2)",
    });
  }
});

export function UploadPanel({ projectKey, onClose }: { projectKey: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const idempotencyKey = useMemo(() => crypto.randomUUID(), []);

  const form = useForm<DatasetMetaValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      description: "",
      classification: "none",
      bbn_level: "",
      confidentiality: "",
      legal_basis: "",
      purpose_codes: "",
    },
  });

  const upload = useMutation({
    mutationFn: (file: File) =>
      createUpload({ path: { key: projectKey }, body: { file }, throwOnError: true }),
    onSuccess: (response) => {
      const result = response.data as UploadOut;
      if (!form.formState.dirtyFields.name) {
        form.setValue("name", slugifyName(result.filename));
      }
    },
  });

  const create = useMutation({
    mutationFn: (values: DatasetMetaValues) => {
      const uploadId = (upload.data?.data as UploadOut).upload_id;
      return createDataset({
        path: { key: projectKey },
        body: { ...toDatasetMeta(values), source: { kind: "upload", upload_id: uploadId } },
        headers: { "Idempotency-Key": idempotencyKey },
        throwOnError: true,
      });
    },
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({
        queryKey: listDatasetsQueryKey({ path: { key: projectKey } }),
      });
      toast({ title: "Dataset created", severity: "success" });
      void navigate({
        to: "/p/$key/datasets/$datasetName",
        params: { key: projectKey, datasetName: response.data.name },
      });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't create the dataset"),
  });

  const uploadResult = upload.data?.data as UploadOut | undefined;
  const uploadProblem = upload.isError ? asProblem(upload.error) : null;

  return (
    <aside
      data-testid="upload-panel"
      aria-label="Upload file"
      className="w-[26rem] shrink-0 self-start rounded-lg border border-border bg-surface p-4 shadow-1"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Upload file</h2>
        <Button variant="ghost" size="sm" aria-label="Close panel" onClick={onClose}>
          <X aria-hidden className="size-4" />
        </Button>
      </div>

      <div className="mt-4 space-y-4">
        <Field
          label="File"
          hint="CSV, Parquet, or Excel. The server infers a typed schema before anything is created."
        >
          <input
            data-testid="upload-file-input"
            type="file"
            accept=".csv,.parquet,.xlsx"
            className="w-full cursor-pointer rounded-md border border-border bg-surface text-sm text-muted file:mr-3 file:h-control file:cursor-pointer file:rounded-l-md file:border-0 file:bg-bg-subtle file:px-3 file:text-sm file:font-medium file:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload.mutate(file);
            }}
          />
        </Field>

        {upload.isPending && (
          <p className="flex items-center gap-2 text-sm text-muted" aria-live="polite">
            <Spinner /> Uploading…
          </p>
        )}

        {uploadProblem && (
          <div
            role="alert"
            className="rounded-md border border-status-danger/40 p-3 text-sm"
          >
            <p className="font-medium">{uploadProblem.title ?? "Upload failed"}</p>
            {uploadProblem.detail && <p className="mt-1 text-muted">{uploadProblem.detail}</p>}
            {uploadProblem.hint && <p className="mt-1 text-muted">{uploadProblem.hint}</p>}
          </div>
        )}

        {uploadResult && (
          <>
            <SchemaPreview
              columns={uploadResult.columns}
              preview={uploadResult.preview}
              testId="upload-preview"
            />
            <form
              className="space-y-4"
              onSubmit={form.handleSubmit((values) => create.mutate(values))}
            >
              <DatasetMetaFields form={form} />
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  data-testid="dataset-create-confirm"
                  loading={create.isPending}
                >
                  Create dataset
                </Button>
              </div>
            </form>
          </>
        )}
      </div>
    </aside>
  );
}
