// @osaip/canvas — the shared, brand-neutral graph canvas (§6.3(1), §6.4). The Flow
// renders it today; the agent builder (Phase 6) reuses the same nodes, edges, and
// layout. Keep this surface domain-free.
export { GraphCanvas, type GraphCanvasProps } from "./GraphCanvas";
export { GraphNodeView } from "./GraphNode";
export { layout, NODE_WIDTH, NODE_HEIGHT, type LayoutOptions } from "./layout";
export { buildNode, buildEdge, type BuildNodeInput, type BuildEdgeInput } from "./builders";
export {
  NODE_TYPE,
  type GraphNode,
  type GraphEdge,
  type GraphNodeData,
  type NodeStatus,
  type NodeDomain,
  type NodeShape,
} from "./types";
