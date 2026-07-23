// The one custom node (§6.3(1)): a domain-color stripe, a status ring + dot, and
// optional badges. Colors are resolved to design tokens (CSS variables) and applied
// as inline custom properties so the node theme-switches with the host with zero
// literals. Brand-neutral — Phase 6's agent builder renders the same node.
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { CSSProperties } from "react";
import type { GraphNode, NodeDomain, NodeStatus } from "./types";

const STATUS_TOKEN: Record<NodeStatus, string> = {
  ok: "var(--color-status-success)",
  running: "var(--color-status-info)",
  failed: "var(--color-status-danger)",
  stale: "var(--color-status-warning)",
  queued: "var(--color-text-faint)",
};

const DOMAIN_TOKEN: Record<NodeDomain, string> = {
  data: "var(--color-accent)",
  ai: "var(--color-status-info)",
  ml: "var(--color-status-success)",
  io: "var(--color-status-warning)",
};

const STATUS_LABEL: Record<NodeStatus, string> = {
  ok: "up to date",
  running: "building",
  failed: "failed",
  stale: "stale",
  queued: "not built",
};

function classNames(...values: Array<string | false | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function GraphNodeView({ data, selected }: NodeProps<GraphNode>) {
  return (
    <div
      data-testid="flow-node"
      data-node-status={data.status}
      className={classNames(
        "osaip-node",
        selected && "is-selected",
        data.shape === "process" && "is-process",
        data.status === "running" && "is-running",
      )}
      style={
        {
          "--osaip-node-status": STATUS_TOKEN[data.status],
          "--osaip-node-domain": DOMAIN_TOKEN[data.domain],
        } as CSSProperties
      }
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <span className="osaip-node__stripe" aria-hidden />
      <div className="osaip-node__body">
        <div className="osaip-node__title">
          <span
            className="osaip-node__dot"
            role="img"
            aria-label={STATUS_LABEL[data.status]}
            title={STATUS_LABEL[data.status]}
          />
          <span className="osaip-node__label">{data.label}</span>
        </div>
        {data.kind ? <div className="osaip-node__meta">{data.kind}</div> : null}
        {data.badges && data.badges.length > 0 ? (
          <div className="osaip-node__badges">
            {data.badges.map((badge) => (
              <span key={badge} className="osaip-node__badge">
                {badge}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}
