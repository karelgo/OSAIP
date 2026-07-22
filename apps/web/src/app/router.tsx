// Route tree (§6.2 IA). Everything is deep-linkable; auth is enforced at the
// `_authed` layout via /me (BFF session cookie, ADR-0001).
import { getMeOptions } from "@osaip/api-client";
import type { QueryClient } from "@tanstack/react-query";
import {
  Outlet,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
} from "@tanstack/react-router";
import { isUnauthenticated } from "../features/auth/api";
import { LoginPage } from "../features/auth/LoginPage";
import { HubPage } from "../features/hub/HubPage";
import { ProjectHome } from "../features/projects/ProjectHome";
import { ProjectsHome } from "../features/projects/ProjectsHome";
import { ProjectSettings } from "../features/projects/ProjectSettings";
import { AppShell } from "../features/shell/AppShell";
import { StubPage } from "../features/shell/StubPage";

interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search): { next?: string } =>
    typeof search.next === "string" ? { next: search.next } : {},
  component: LoginPage,
});

const authedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "_authed",
  beforeLoad: async ({ context, location }) => {
    try {
      await context.queryClient.ensureQueryData({ ...getMeOptions(), retry: false });
    } catch (error) {
      if (isUnauthenticated(error)) {
        throw redirect({ to: "/login", search: { next: location.href } });
      }
      throw error;
    }
  },
  component: Outlet,
});

// Hub: consumer surface, zero studio chrome (§6.1)
const hubRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/hub",
  component: HubPage,
});

const shellRoute = createRoute({
  getParentRoute: () => authedRoute,
  id: "_shell",
  component: AppShell,
});

const indexRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/",
  validateSearch: (search): { new?: boolean } => (search.new === true ? { new: true } : {}),
  component: ProjectsHome,
});

const projectRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: "/p/$key",
  component: Outlet,
});

const projectIndexRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/",
  component: ProjectHome,
});

const projectSettingsRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/settings",
  component: ProjectSettings,
});

// Modules that ship in later phases: real routes, designed placeholder pages (§6.7).
const STUBS: Array<[string, string, number]> = [
  ["datasets", "Datasets", 1],
  ["notebooks", "Notebooks", 9],
  ["knowledge", "Knowledge banks", 4],
  ["semantic", "Semantic models", 5],
  ["agents", "Agents", 6],
  ["prompts", "Prompts & tools", 3],
  ["evals", "Evaluations", 7],
  ["traces", "Traces", 6],
  ["answers", "Answers apps", 4],
  ["hub-admin", "Hub administration", 7],
  ["ml", "ML Lab", 10],
  ["scenarios", "Scenarios", 8],
  ["jobs", "Jobs", 2],
  ["deployments", "Deployments", 7],
  ["monitoring", "Monitoring", 7],
  ["dashboards", "Dashboards", 12],
];

const stubRoutes = STUBS.map(([path, title, phase]) =>
  createRoute({
    getParentRoute: () => projectRoute,
    path: `/${path}`,
    component: () => <StubPage title={title} phase={phase} />,
  }),
);

// A dataset detail stub so seeded ⌘K results resolve to a real page (AC-6).
const datasetDetailRoute = createRoute({
  getParentRoute: () => projectRoute,
  path: "/datasets/$datasetName",
  component: DatasetStub,
});

function DatasetStub() {
  const { datasetName } = datasetDetailRoute.useParams();
  return <StubPage title={`Dataset ${datasetName}`} phase={1} />;
}

const routeTree = rootRoute.addChildren([
  loginRoute,
  authedRoute.addChildren([
    hubRoute,
    shellRoute.addChildren([
      indexRoute,
      projectRoute.addChildren([
        projectIndexRoute,
        projectSettingsRoute,
        datasetDetailRoute,
        ...stubRoutes,
      ]),
    ]),
  ]),
]);

export function makeRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}
