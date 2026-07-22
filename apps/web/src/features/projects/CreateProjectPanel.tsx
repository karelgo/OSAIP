// Inspector-style creation panel (react-hook-form + zod per §3.2; optimistic-adjacent:
// Idempotency-Key makes retries safe, §6.5).
import { Button, Field, Input, toast } from "@osaip/ui";
import { createProject, listProjectsQueryKey } from "@osaip/api-client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

const schema = z.object({
  key: z
    .string()
    .min(2, "Key needs at least 2 characters")
    .max(64)
    .regex(
      /^[a-z][a-z0-9_-]{1,63}$/,
      "Lowercase letters, digits, - and _; must start with a letter",
    ),
  name: z.string().min(1, "Give the project a name").max(200),
  description: z.string().max(10_000),
});

type FormValues = z.infer<typeof schema>;

export function CreateProjectPanel({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const idempotencyKey = useMemo(() => crypto.randomUUID(), []);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { key: "", name: "", description: "" },
  });

  const create = useMutation({
    mutationFn: (values: FormValues) =>
      createProject({
        body: values,
        headers: { "Idempotency-Key": idempotencyKey },
        throwOnError: true,
      }),
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({ queryKey: listProjectsQueryKey() });
      toast({ title: "Project created", severity: "success" });
      void navigate({ to: "/p/$key", params: { key: response.data.key as string } });
    },
    onError: (error: unknown) => {
      const problem = error as { title?: string; hint?: string };
      toast({
        title: problem.title ?? "Couldn't create the project",
        description: problem.hint,
        severity: "error",
      });
    },
  });

  return (
    <aside
      data-testid="create-project-panel"
      aria-label="New project"
      className="w-80 shrink-0 rounded-lg border border-border bg-surface p-4 shadow-1"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">New project</h2>
        <Button variant="ghost" size="sm" aria-label="Close panel" onClick={onClose}>
          <X aria-hidden className="size-4" />
        </Button>
      </div>
      <form
        className="mt-4 space-y-4"
        onSubmit={form.handleSubmit((values) => create.mutate(values))}
      >
        <Field label="Name" error={form.formState.errors.name?.message}>
          <Input
            data-testid="project-name-input"
            placeholder="Customer analytics"
            {...form.register("name", {
              onChange: (event) => {
                if (!form.formState.dirtyFields.key) {
                  form.setValue(
                    "key",
                    String(event.target.value)
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, "-")
                      .replace(/^[^a-z]+/, "")
                      .replace(/-+$/, "")
                      .slice(0, 64),
                  );
                }
              },
            })}
          />
        </Field>
        <Field
          label="Key"
          error={form.formState.errors.key?.message}
          hint="Permanent identifier; used in URLs and storage paths."
        >
          <Input
            data-testid="project-key-input"
            className="font-mono"
            placeholder="customer-analytics"
            {...form.register("key")}
          />
        </Field>
        <Field label="Description" error={form.formState.errors.description?.message}>
          <Input
            data-testid="project-description-input"
            placeholder="What is this project for?"
            {...form.register("description")}
          />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" data-testid="create-project-submit" loading={create.isPending}>
            Create project
          </Button>
        </div>
      </form>
    </aside>
  );
}
