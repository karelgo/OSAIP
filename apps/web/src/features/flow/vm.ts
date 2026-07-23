// Flow view-model: turn the FlowOut DAG into brand-neutral canvas nodes/edges. The
// pure graph helpers (parsing, lineage, empty check) live in graph.ts so the datasets
// feature can reuse them without importing @osaip/canvas; this module adds the one
// canvas-dependent piece — `toGraph` — and re-exports the rest for the flow feature.
import type { FlowDatasetOut, FlowOut, FlowRecipeOut } from "@osaip/api-client";
import { buildEdge, buildNode, type GraphEdge, type GraphNode, type NodeStatus } from "@osaip/canvas";
import { datasetNodeId, datasetStatus, recipeNodeId } from "./graph";

export * from "./graph";

/** A recipe's ring reflects the worst state across its outputs (running > failed > stale > …). */
function recipeStatus(recipe: FlowRecipeOut, byName: Map<string, FlowDatasetOut>): NodeStatus {
  const outputs = recipe.output_datasets
    .map((name) => byName.get(name))
    .filter((dataset): dataset is FlowDatasetOut => dataset !== undefined)
    .map((dataset) => datasetStatus(dataset.status));
  const order: NodeStatus[] = ["running", "failed", "stale", "queued", "ok"];
  for (const candidate of order) {
    if (outputs.includes(candidate)) return candidate;
  }
  return "queued";
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export function toGraph(flow: FlowOut): Graph {
  const byName = new Map(flow.datasets.map((dataset) => [dataset.name, dataset]));
  const runningNodes = new Set<string>();

  const datasetNodes = flow.datasets.map((dataset) => {
    const status = datasetStatus(dataset.status);
    const id = datasetNodeId(dataset.name);
    if (status === "running") runningNodes.add(id);
    const badges: string[] = [];
    if (dataset.classification && dataset.classification !== "none") badges.push(dataset.classification);
    if (dataset.bbn_level) badges.push(dataset.bbn_level);
    return buildNode({
      id,
      label: dataset.name,
      domain: "data",
      status,
      shape: "artifact",
      kind: dataset.kind,
      badges,
    });
  });

  const recipeNodes = flow.recipes.map((recipe) => {
    const status = recipeStatus(recipe, byName);
    const id = recipeNodeId(recipe.id);
    if (status === "running") runningNodes.add(id);
    return buildNode({
      id,
      label: recipe.name,
      domain: "data",
      status,
      shape: "process",
      kind: recipe.kind,
    });
  });

  // Living Flow (§6.4): an edge pulses when either endpoint is in the running subgraph.
  const edges = flow.edges.map((edge) =>
    buildEdge({
      source: edge.from,
      target: edge.to,
      animated: runningNodes.has(edge.from) || runningNodes.has(edge.to),
    }),
  );

  return { nodes: [...datasetNodes, ...recipeNodes], edges };
}
