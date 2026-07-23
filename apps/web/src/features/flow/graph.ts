// Pure graph helpers — NO @osaip/canvas import, so the datasets feature (in the entry
// chunk) can reuse them for its Lineage tab without dragging @xyflow into the bundle.
// The canvas-dependent builder (`toGraph`) lives in vm.ts alongside these re-exports.
// Type-only imports are erased at build time, so pulling NodeStatus from @osaip/canvas
// here does NOT bundle @xyflow into the entry chunk.
import type { FlowOut } from "@osaip/api-client";
import type { NodeStatus } from "@osaip/canvas";

export const DATASET_PREFIX = "dataset:";
export const RECIPE_PREFIX = "recipe:";

export function datasetNodeId(name: string): string {
  return `${DATASET_PREFIX}${name}`;
}
export function recipeNodeId(id: string): string {
  return `${RECIPE_PREFIX}${id}`;
}

export type Selection =
  | { kind: "dataset"; name: string }
  | { kind: "recipe"; id: string }
  | null;

/** Parse a `?sel` node id into a typed selection. */
export function parseSelection(sel: string | undefined): Selection {
  if (!sel) return null;
  if (sel.startsWith(DATASET_PREFIX)) return { kind: "dataset", name: sel.slice(DATASET_PREFIX.length) };
  if (sel.startsWith(RECIPE_PREFIX)) return { kind: "recipe", id: sel.slice(RECIPE_PREFIX.length) };
  return null;
}

const SOURCE_STATUSES = new Set(["source", "source_empty"]);

/** Map a Flow dataset status onto a canvas status ring state. */
export function datasetStatus(status: string): NodeStatus {
  switch (status) {
    case "building":
      return "running";
    case "failed":
      return "failed";
    case "stale":
      return "stale";
    case "fresh":
    case "source":
      return "ok";
    case "never_built":
    case "source_empty":
      return "queued";
    default:
      return "queued";
  }
}

export function isSourceStatus(status: string): boolean {
  return SOURCE_STATUSES.has(status);
}

/**
 * Empty graph = nothing has been built yet: no recipes AND every dataset is still a
 * bare source. That's when `/p/$key` shows onboarding instead of the living Flow.
 */
export function isEmptyGraph(flow: FlowOut): boolean {
  const hasProduced = flow.datasets.some((dataset) => !SOURCE_STATUSES.has(dataset.status));
  return flow.recipes.length === 0 && !hasProduced;
}

export interface Neighbors {
  upstream: string[];
  downstream: string[];
}

/** Immediate upstream inputs and downstream consumers of a node id (one hop). */
export function neighbors(flow: FlowOut, nodeId: string): Neighbors {
  return {
    upstream: flow.edges.filter((edge) => edge.to === nodeId).map((edge) => edge.from),
    downstream: flow.edges.filter((edge) => edge.from === nodeId).map((edge) => edge.to),
  };
}

/** Human label for a node id, resolved against the flow. */
export function nodeLabel(flow: FlowOut, nodeId: string): string {
  const selection = parseSelection(nodeId);
  if (selection?.kind === "dataset") return selection.name;
  if (selection?.kind === "recipe") {
    return flow.recipes.find((recipe) => recipe.id === selection.id)?.name ?? "recipe";
  }
  return nodeId;
}
