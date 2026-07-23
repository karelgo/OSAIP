// Reusable graph canvas (§6.3(1), §6.4). Wraps @xyflow/react with the OSAIP node,
// a keyboard model (arrows move a focus cursor, Enter opens the inspector), and
// token-driven theming. The Flow uses it now; the agent builder (Phase 6) reuses it.
import { Background, Controls, ReactFlow, type NodeTypes } from "@xyflow/react";
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { GraphNodeView } from "./GraphNode";
import { NODE_TYPE, type GraphEdge, type GraphNode } from "./types";
import "@xyflow/react/dist/style.css";
import "./canvas.css";

export interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** The committed selection (its inspector is open). `dataset:<name>` | `recipe:<id>`. */
  selectedId?: string | null;
  /** Fired on click and on Enter over the keyboard cursor; null on empty-pane click. */
  onSelect?: (id: string | null) => void;
  /** Resolved viewer theme, forwarded to xyflow's color mode. */
  colorMode?: "light" | "dark";
  className?: string;
  "data-testid"?: string;
}

// The custom node is typed for GraphNode specifically; xyflow's NodeTypes wants the
// generic NodeProps, so the registration is cast (standard for custom-typed nodes).
const nodeTypes = { [NODE_TYPE]: GraphNodeView } as unknown as NodeTypes;

type Direction = "left" | "right" | "up" | "down";

/** Nearest node in a direction from an anchor, by primary-axis then perpendicular gap. */
function nextInDirection(
  nodes: GraphNode[],
  fromId: string | null,
  direction: Direction,
): string | null {
  if (nodes.length === 0) return null;
  const anchor = fromId ? nodes.find((node) => node.id === fromId) : undefined;
  if (!anchor) return nodes[0]?.id ?? null;

  const scored = nodes
    .filter((node) => node.id !== fromId)
    .map((node) => ({
      id: node.id,
      dx: node.position.x - anchor.position.x,
      dy: node.position.y - anchor.position.y,
    }))
    .filter(({ dx, dy }) => {
      if (direction === "right") return dx > 1;
      if (direction === "left") return dx < -1;
      if (direction === "down") return dy > 1;
      return dy < -1;
    });
  if (scored.length === 0) return null;

  const horizontal = direction === "left" || direction === "right";
  scored.sort((a, b) => {
    const primaryA = horizontal ? Math.abs(a.dx) : Math.abs(a.dy);
    const primaryB = horizontal ? Math.abs(b.dx) : Math.abs(b.dy);
    const perpA = horizontal ? Math.abs(a.dy) : Math.abs(a.dx);
    const perpB = horizontal ? Math.abs(b.dy) : Math.abs(b.dx);
    return primaryA - primaryB || perpA - perpB;
  });
  return scored[0]?.id ?? null;
}

const ARROWS: Record<string, Direction> = {
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowUp: "up",
  ArrowDown: "down",
};

export function GraphCanvas({
  nodes,
  edges,
  selectedId = null,
  onSelect,
  colorMode = "light",
  className,
  "data-testid": testId = "flow-canvas",
}: GraphCanvasProps) {
  const [focusedId, setFocusedId] = useState<string | null>(selectedId);
  const [seenSelected, setSeenSelected] = useState<string | null>(selectedId);
  const containerRef = useRef<HTMLDivElement>(null);

  // Follow the committed selection when it changes from the outside (deep link, click)
  // by adjusting state during render — the React-recommended alternative to a sync
  // setState inside an effect.
  if (selectedId !== seenSelected) {
    setSeenSelected(selectedId);
    if (selectedId) setFocusedId(selectedId);
  }

  const renderNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        selected: node.id === selectedId,
        className: node.id === focusedId ? "osaip-focused" : undefined,
      })),
    [nodes, selectedId, focusedId],
  );

  const handleKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      const direction = ARROWS[event.key];
      if (direction) {
        event.preventDefault();
        const next = nextInDirection(nodes, focusedId, direction);
        if (next) setFocusedId(next);
        return;
      }
      if (event.key === "Enter" && focusedId) {
        event.preventDefault();
        onSelect?.(focusedId);
      }
    },
    [nodes, focusedId, onSelect],
  );

  const handleNodeClick = useCallback(
    (_event: ReactMouseEvent, node: GraphNode) => {
      setFocusedId(node.id);
      onSelect?.(node.id);
    },
    [onSelect],
  );

  const handlePaneClick = useCallback(() => onSelect?.(null), [onSelect]);

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      role="application"
      aria-label="Flow graph — arrow keys move between nodes, Enter opens the inspector"
      data-testid={testId}
      className={className}
      onKeyDown={handleKeyDown}
      style={{ width: "100%", height: "100%", outline: "none" }}
    >
      <ReactFlow
        className="osaip-flow"
        colorMode={colorMode}
        nodes={renderNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        fitView
        minZoom={0.2}
        maxZoom={1.6}
        proOptions={{ hideAttribution: true }}
        // Own the keyboard on the wrapper; xyflow's node a11y would fight the cursor.
        disableKeyboardA11y
      >
        <Background gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
