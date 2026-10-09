// A layered layout for a call graph: callers above, the services they call below.
// Edges run caller -> callee, so a fault travels upwards on screen, from the broken
// service to the ones that only feel it.
import type { Edge } from "../api/types";

export interface Placed {
  id: string;
  x: number;
  y: number;
  layer: number;
}

export const LAYER_GAP = 90;
export const NODE_GAP = 140;

/**
 * Layer = length of the longest path from a root (a service nobody calls). Services
 * on a cycle or with no edges at all are placed on the last layer, so nothing is
 * lost. Within a layer services keep alphabetical order, for a stable picture.
 */
export function layoutGraph(services: string[], edges: Edge[]): Placed[] {
  const all = Array.from(new Set([...services, ...edges.flatMap((e) => [e.from, e.to])])).sort();
  const callers = new Map<string, string[]>();
  for (const s of all) {
    callers.set(s, []);
  }
  for (const e of edges) {
    if (e.from !== e.to) {
      callers.get(e.to)!.push(e.from);
    }
  }

  const layer = new Map<string, number>();
  const visiting = new Set<string>();
  const depth = (s: string): number => {
    if (layer.has(s)) {
      return layer.get(s)!;
    }
    if (visiting.has(s)) {
      return 0; // a cycle: stop rather than loop
    }
    visiting.add(s);
    const parents = callers.get(s) ?? [];
    const d = parents.length === 0 ? 0 : 1 + Math.max(...parents.map(depth));
    visiting.delete(s);
    layer.set(s, d);
    return d;
  };
  const connected = new Set(edges.flatMap((e) => [e.from, e.to]));
  for (const s of all) {
    depth(s);
  }
  const maxLayer = Math.max(0, ...all.filter((s) => connected.has(s)).map((s) => layer.get(s)!));
  for (const s of all) {
    if (!connected.has(s)) {
      layer.set(s, maxLayer + 1);
    }
  }

  const byLayer = new Map<number, string[]>();
  for (const s of all) {
    const l = layer.get(s)!;
    byLayer.set(l, [...(byLayer.get(l) ?? []), s]);
  }
  const widest = Math.max(...Array.from(byLayer.values()).map((v) => v.length));
  const placed: Placed[] = [];
  for (const [l, names] of byLayer) {
    const offset = ((widest - names.length) * NODE_GAP) / 2;
    names.forEach((name, i) => placed.push({ id: name, x: offset + i * NODE_GAP, y: l * LAYER_GAP, layer: l }));
  }
  return placed;
}
