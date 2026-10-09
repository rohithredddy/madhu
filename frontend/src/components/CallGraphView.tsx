import { useMemo } from "react";
import { Handle, MarkerType, Position, ReactFlow, type Edge as FlowEdge, type Node, type NodeProps } from "@xyflow/react";
import type { CallGraph, Role, ServiceRanking } from "../api/types";
import { layoutGraph } from "../lib/graphLayout";
import { cssVar } from "../lib/colors";
import { one, roleLabel } from "../lib/format";

type ServiceData = {
  name: string;
  role: Role | null;
  truth: boolean;
  score: number | null;
  marginal: number | null;
};

/** One service: coloured by its role, with a green ring when it is the known answer. */
function ServiceNode({ data }: NodeProps<Node<ServiceData>>) {
  const role = data.role ?? "NORMAL";
  const title = data.role
    ? `${data.name}: ${roleLabel(role)}, own score ${one(data.score)}, looks ${one(data.marginal)} unusual`
    : data.name;
  return (
    <div className={`service-node role-${role}${data.truth ? " truth" : ""}`} title={title}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      {data.name}
      {data.role && <span className="score">{one(data.score)}</span>}
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { service: ServiceNode };

/**
 * The call graph with each service coloured by what the analysis concluded (docs/04
 * section 3.3). Callers sit above the services they call, so a fault travels upward.
 * Without a result it shows the bare graph.
 */
export function CallGraphView({
  graph,
  services,
  ranking,
  truthService,
  tall = false,
}: {
  graph: CallGraph;
  services: string[];
  ranking?: ServiceRanking[];
  truthService?: string | null;
  tall?: boolean;
}) {
  const { nodes, edges } = useMemo(() => {
    const byName = new Map((ranking ?? []).map((r) => [r.service, r]));
    const placed = layoutGraph(services, graph.edges);
    const nodes: Node<ServiceData>[] = placed.map((p) => {
      const r = byName.get(p.id);
      return {
        id: p.id,
        type: "service",
        position: { x: p.x, y: p.y },
        data: {
          name: p.id,
          role: r ? r.role : null,
          truth: !!truthService && truthService === p.id,
          score: r?.score ?? null,
          marginal: r?.marginalScore ?? null,
        },
        draggable: false,
      };
    });
    const line = cssVar("--ink-3");
    const edges: FlowEdge[] = graph.edges.map((e) => ({
      id: `${e.from}->${e.to}`,
      source: e.from,
      target: e.to,
      markerEnd: { type: MarkerType.ArrowClosed, color: line },
      style: { stroke: line, strokeWidth: 1.5 },
    }));
    return { nodes, edges };
  }, [graph, services, ranking, truthService]);

  return (
    <div>
      <div className={`graph-box${tall ? " tall" : ""}`}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          nodesConnectable={false}
          elementsSelectable={false}
          minZoom={0.2}
        />
      </div>
      <div className="legend" aria-label="Legend">
        <span>
          <span className="swatch" style={{ background: "var(--cause)" }} />
          cause
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--symptom)" }} />
          symptom (affected)
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--also-abnormal)" }} />
          also abnormal
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--normal)" }} />
          normal
        </span>
        {truthService && (
          <span>
            <span className="swatch truth-ring" />
            known answer
          </span>
        )}
        <span>arrow: caller → service it calls</span>
        {graph.edges.length === 0 && <span>No call graph is available for this system.</span>}
      </div>
    </div>
  );
}
