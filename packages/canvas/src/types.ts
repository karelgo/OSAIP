// Brand-neutral graph vocabulary (§6.3(1)). The Flow reuses these today; the agent
// builder (Phase 6) reuses the SAME node/edge shape — nothing here names datasets or
// recipes, only the visual axes every module shares: a domain, a status, a shape.
import type { Edge, Node } from "@xyflow/react";

/** Status ring states (§6.3(1)). Consumers map their domain status onto these five. */
export type NodeStatus = "queued" | "running" | "ok" | "failed" | "stale";

/** Domain color stripe. Only `data` renders in Phase 2; ai/ml/io land with later modules. */
export type NodeDomain = "data" | "ai" | "ml" | "io";

/** Silhouette: producers (recipes/steps) read differently from artifacts (datasets). */
export type NodeShape = "artifact" | "process";

export interface GraphNodeData extends Record<string, unknown> {
  label: string;
  domain: NodeDomain;
  status: NodeStatus;
  shape: NodeShape;
  /** Short type line under the label, e.g. a recipe kind or dataset kind. */
  kind?: string;
  /** Small pills on the node — classification and the like. */
  badges?: string[];
}

/** The one xyflow node type the canvas registers. */
export const NODE_TYPE = "osaip" as const;

export type GraphNode = Node<GraphNodeData, typeof NODE_TYPE>;
export type GraphEdge = Edge;
