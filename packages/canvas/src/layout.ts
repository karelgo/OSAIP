// Dagre layout behind a stable, SYNCHRONOUS interface (§6.5). Graphs are small in
// Phase 2, so a main-thread pass is imperceptible; when they grow large enough to
// jank, this moves to a web worker WITHOUT changing callers — the contract stays
// "give me nodes + edges, get positioned nodes back".
import Dagre from "@dagrejs/dagre";
import type { GraphEdge, GraphNode } from "./types";

export const NODE_WIDTH = 220;
export const NODE_HEIGHT = 72;

export interface LayoutOptions {
  /** Left-to-right ranks by default: sources on the left, outputs on the right. */
  direction?: "LR" | "TB";
}

export function layout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  options: LayoutOptions = {},
): GraphNode[] {
  const graph = new Dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    rankdir: options.direction ?? "LR",
    nodesep: 36,
    ranksep: 96,
    marginx: 24,
    marginy: 24,
  });

  for (const node of nodes) {
    graph.setNode(node.id, {
      width: node.width ?? node.measured?.width ?? NODE_WIDTH,
      height: node.height ?? node.measured?.height ?? NODE_HEIGHT,
    });
  }
  for (const edge of edges) graph.setEdge(edge.source, edge.target);

  Dagre.layout(graph);

  return nodes.map((node) => {
    const positioned = graph.node(node.id) as
      | { x?: number; y?: number; width?: number; height?: number }
      | undefined;
    if (!positioned || positioned.x === undefined || positioned.y === undefined) {
      return node;
    }
    const width = positioned.width ?? NODE_WIDTH;
    const height = positioned.height ?? NODE_HEIGHT;
    // dagre centers nodes; xyflow positions by the top-left corner.
    return { ...node, position: { x: positioned.x - width / 2, y: positioned.y - height / 2 } };
  });
}
