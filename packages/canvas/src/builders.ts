// Node/edge builders — the stable construction surface consumers use so they never
// hand-assemble xyflow objects (keeps the `type`/id conventions in one place).
import { NODE_TYPE, type GraphEdge, type GraphNode, type GraphNodeData } from "./types";

export interface BuildNodeInput extends GraphNodeData {
  id: string;
}

/** Build a positioned-at-origin node; `layout()` assigns real coordinates. */
export function buildNode({ id, ...data }: BuildNodeInput): GraphNode {
  return { id, type: NODE_TYPE, position: { x: 0, y: 0 }, data };
}

export interface BuildEdgeInput {
  source: string;
  target: string;
  /** Living Flow (§6.4): a running subgraph animates a pulse along its edges. */
  animated?: boolean;
}

export function buildEdge({ source, target, animated = false }: BuildEdgeInput): GraphEdge {
  return { id: `${source}~>${target}`, source, target, animated };
}
