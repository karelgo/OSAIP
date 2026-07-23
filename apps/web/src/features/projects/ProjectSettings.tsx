// Project settings: General · Members · Connections · Audit — the canonical tab
// order pattern the inspector reuses later (§6.3(2)). The active tab lives in the
// URL (?tab=, §6.7 deep-linkable). Capability flags from the server drive what is
// editable; viewers see read-only affordances, never hidden-broken buttons (§6.1).
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@osaip/ui";
import {
  archiveProject,
  getProjectOptions,
  getProjectQueryKey,
  listMembersOptions,
  listMembersQueryKey,
  listProjectsQueryKey,
  patchProject,
  projectAuditOptions,
  removeMember,
  replaceMembers,
} from "@osaip/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { AlertTriangle, Archive, UserPlus } from "lucide-react";
import { useState } from "react";
import type { SettingsTab } from "../../app/router";
import { ConnectionsTab } from "./ConnectionsTab";

export function ProjectSettings() {
  const { key } = useParams({ from: "/_authed/_shell/p/$key/settings" });
  const search = useSearch({ from: "/_authed/_shell/p/$key/settings" });
  const navigate = useNavigate();
  const project = useQuery(getProjectOptions({ path: { key } }));

  if (project.isLoading) {
    return (
      <div className="p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="mt-4 h-64 w-full" />
      </div>
    );
  }
  if (project.isError || !project.data) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <EmptyState
          icon={<AlertTriangle aria-hidden className="size-8" />}
          title="Couldn't load settings"
          description="Check that you still have access to this project."
        >
          <Button variant="secondary" onClick={() => project.refetch()}>
            Retry
          </Button>
        </EmptyState>
      </div>
    );
  }

  const capabilities = project.data.capabilities;
  const tab: SettingsTab = search.tab ?? "general";

  function setTab(next: string) {
    void navigate({
      to: "/p/$key/settings",
      params: { key },
      search: next === "general" ? {} : { tab: next as SettingsTab },
      replace: true,
    });
  }

  return (
    <div className="mx-auto max-w-4xl p-6" data-testid="project-settings">
      <h1 className="text-xl font-semibold tracking-tight">Project settings</h1>
      <Tabs value={tab} onValueChange={setTab} className="mt-6">
        <TabsList>
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="members" data-testid="members-tab">
            Members
          </TabsTrigger>
          <TabsTrigger value="connections" data-testid="connections-tab">
            Connections
          </TabsTrigger>
          <TabsTrigger value="audit" data-testid="audit-tab">
            Audit
          </TabsTrigger>
        </TabsList>
        <TabsContent value="general">
          <GeneralTab projectKey={key} canEdit={capabilities.can_edit} canArchive={capabilities.can_archive} />
        </TabsContent>
        <TabsContent value="members">
          <MembersTab projectKey={key} canManage={capabilities.can_manage_members} />
        </TabsContent>
        <TabsContent value="connections">
          <ConnectionsTab projectKey={key} canManage={capabilities.can_manage_connections} />
        </TabsContent>
        <TabsContent value="audit">
          <AuditTab projectKey={key} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function GeneralTab({
  projectKey,
  canEdit,
  canArchive,
}: {
  projectKey: string;
  canEdit: boolean;
  canArchive: boolean;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const project = useQuery(getProjectOptions({ path: { key: projectKey } }));
  const [name, setName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      patchProject({
        path: { key: projectKey },
        body: {
          ...(name !== null ? { name } : {}),
          ...(description !== null ? { description } : {}),
        },
        throwOnError: true,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: getProjectQueryKey({ path: { key: projectKey } }) });
      await queryClient.invalidateQueries({ queryKey: listProjectsQueryKey() });
      toast({ title: "Changes saved", severity: "success" });
    },
    onError: (error: unknown) => {
      const problem = error as { title?: string; hint?: string };
      toast({ title: problem.title ?? "Couldn't save changes", description: problem.hint, severity: "error" });
    },
  });

  const archive = useMutation({
    mutationFn: () => archiveProject({ path: { key: projectKey }, throwOnError: true }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: listProjectsQueryKey() });
      toast({ title: "Project archived", severity: "info" });
      void navigate({ to: "/" });
    },
  });

  const data = project.data;
  if (!data) return null;

  return (
    <div className="mt-4 space-y-6">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Name">
          <Input
            data-testid="settings-name-input"
            defaultValue={data.name}
            disabled={!canEdit}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Field label="Description">
          <Input
            defaultValue={data.description}
            disabled={!canEdit}
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>
        <Field label="Key">
          <Input className="font-mono" value={data.key} disabled readOnly />
        </Field>
        {canEdit && (
          <Button type="submit" data-testid="settings-save" loading={save.isPending} disabled={name === null && description === null}>
            Save changes
          </Button>
        )}
      </form>

      {canArchive && (
        <div className="rounded-lg border border-status-danger/40 p-4">
          <h3 className="text-sm font-medium">Archive this project</h3>
          <p className="mt-1 text-sm text-muted">
            Archived projects become read-only and leave search. This is reversible only by a
            site administrator.
          </p>
          <ConfirmDialog
            title="Archive project?"
            description={`"${data.name}" becomes read-only for every member.`}
            confirmLabel="Archive project"
            destructive
            onConfirm={() => archive.mutate()}
            trigger={
              <Button variant="danger" className="mt-3" data-testid="archive-project">
                <Archive aria-hidden className="size-4" /> Archive project
              </Button>
            }
          />
        </div>
      )}
    </div>
  );
}

function MembersTab({ projectKey, canManage }: { projectKey: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const members = useQuery(listMembersOptions({ path: { key: projectKey } }));
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: listMembersQueryKey({ path: { key: projectKey } }) });
  }

  const put = useMutation({
    mutationFn: (payload: { email: string; role: string }[]) =>
      replaceMembers({ path: { key: projectKey }, body: { members: payload }, throwOnError: true }),
    onSuccess: async () => {
      setEmail("");
      await refresh();
    },
    onError: (error: unknown) => {
      const problem = error as { title?: string; hint?: string };
      toast({ title: problem.title ?? "Couldn't update members", description: problem.hint, severity: "error" });
    },
  });

  const remove = useMutation({
    mutationFn: (userId: string) =>
      removeMember({ path: { key: projectKey, user_id: userId }, throwOnError: true }),
    onSuccess: refresh,
    onError: (error: unknown) => {
      const problem = error as { title?: string; hint?: string };
      toast({ title: problem.title ?? "Couldn't remove member", description: problem.hint, severity: "error" });
    },
  });

  const items = members.data?.items ?? [];

  function currentAsPayload() {
    return items.map((member) => ({ email: member.email, role: member.role }));
  }

  return (
    <div className="mt-4 space-y-4" data-testid="members-list">
      {canManage && (
        <form
          className="flex items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!email) return;
            put.mutate([...currentAsPayload(), { email, role }]);
          }}
        >
          <Field label="Add member by email" className="flex-1">
            <Input
              data-testid="member-email-input"
              type="email"
              placeholder="colleague@example.org"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger className="w-32" aria-label="Role for new member">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="viewer">Viewer</SelectItem>
              <SelectItem value="editor">Editor</SelectItem>
              <SelectItem value="admin">Admin</SelectItem>
            </SelectContent>
          </Select>
          <Button type="submit" data-testid="add-member" loading={put.isPending}>
            <UserPlus aria-hidden className="size-4" /> Add member
          </Button>
        </form>
      )}

      {members.isLoading && <Skeleton className="h-32 w-full" />}
      {members.isSuccess && (
        <Table>
          <THead>
            <TR>
              <TH>Member</TH>
              <TH>Email</TH>
              <TH>Role</TH>
              {canManage && <TH aria-label="Actions" />}
            </TR>
          </THead>
          <TBody>
            {items.map((member) => (
              <TR key={member.user_id} data-testid="member-row">
                <TD className="font-medium">{member.display_name}</TD>
                <TD className="text-muted">{member.email}</TD>
                <TD>
                  {canManage ? (
                    <Select
                      value={member.role}
                      onValueChange={(newRole) =>
                        put.mutate(
                          currentAsPayload().map((entry) =>
                            entry.email === member.email ? { ...entry, role: newRole } : entry,
                          ),
                        )
                      }
                    >
                      <SelectTrigger className="w-28" aria-label={`Role for ${member.email}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="viewer">Viewer</SelectItem>
                        <SelectItem value="editor">Editor</SelectItem>
                        <SelectItem value="admin">Admin</SelectItem>
                      </SelectContent>
                    </Select>
                  ) : (
                    <Badge variant="neutral">{member.role}</Badge>
                  )}
                </TD>
                {canManage && (
                  <TD>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => remove.mutate(member.user_id)}
                      aria-label={`Remove ${member.email}`}
                    >
                      Remove
                    </Button>
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}

function AuditTab({ projectKey }: { projectKey: string }) {
  const audit = useQuery(projectAuditOptions({ path: { key: projectKey } }));
  const items = audit.data?.items ?? [];

  return (
    <div className="mt-4" data-testid="audit-list">
      {audit.isLoading && <Skeleton className="h-40 w-full" />}
      {audit.isSuccess && items.length === 0 && (
        <EmptyState
          title="No audit entries yet"
          description="Every mutation in this project is recorded here, hash-chained for integrity."
        />
      )}
      {items.length > 0 && (
        <Table>
          <THead>
            <TR>
              <TH>When</TH>
              <TH>Action</TH>
              <TH>Object</TH>
              <TH numeric>Seq</TH>
            </TR>
          </THead>
          <TBody>
            {items.map((entry) => (
              <TR key={entry.seq} data-testid="audit-row">
                <TD className="whitespace-nowrap text-muted">
                  {new Date(entry.ts).toLocaleString()}
                </TD>
                <TD className="font-mono text-xs">{entry.action}</TD>
                <TD className="text-muted">
                  {entry.object_kind}
                  {entry.object_id ? ` · ${entry.object_id}` : ""}
                </TD>
                <TD numeric>{entry.seq}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}
