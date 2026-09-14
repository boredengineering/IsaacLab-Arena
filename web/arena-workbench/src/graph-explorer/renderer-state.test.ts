import { describe, expect, it } from 'vitest';
import { createGraphFilters, normalizeGraph, projectGraph } from './graph-model';
import { RendererState } from './renderer-state';
const graph = normalizeGraph({ nodes: ['a', 'b'].map(id => ({ id, label: id, role: 'object', properties: {} })), edges: [] });
const projection = projectGraph(graph, createGraphFilters(graph));

describe('renderer state ownership', () => {
  it('retains mutable DTOs and velocities for selection/search-only projections', () => {
    const state=new RendererState(3,'scope',{positions:new Map(),pins:new Set(),frozen:false});
    const data=state.reconcile(graph,projection); data.nodes[0].vx=17;
    const selected=projectGraph(graph,createGraphFilters(graph),{kind:'node',id:'a'});
    expect(state.reconcile(graph,selected)).toBe(data);
    expect(state.reconcile(graph,projectGraph(graph,{...createGraphFilters(graph),search:'a'}))).toBe(data);
    expect(state.data.nodes[0].vx).toBe(17);
    expect(state.reconcile(graph,{...projection,nodes:projection.nodes.slice(1),edges:[]})).not.toBe(data);
  });
  it('restores the last accepted DTO coordinates after an invalid engine drag end',()=>{
    for(const dimensions of [2,3] as const){
      const state=new RendererState(dimensions,'scope',{positions:new Map(),pins:new Set(),frozen:false});
      state.reconcile(graph,projection);state.move('a',{x:10,y:20,z:30});
      const node=state.data.nodes[0];Object.assign(node,{x:1e6+1,y:NaN,z:Infinity,fx:1e6+1,fy:NaN,fz:Infinity});
      expect(state.move('a',{x:node.x,y:node.y,z:node.z})).toBe(false);
      expect({x:node.x,y:node.y,z:node.z}).toEqual({x:10,y:20,z:dimensions===2?0:30});
      expect(node.fx).toBe(10);expect(node.fy).toBe(20);
      expect(state.snapshot().positions.get('a')).toEqual({x:10,y:20,z:dimensions===2?0:30});
    }
  });
  it('reconciles hidden/returning nodes and drops removed IDs without sharing snapshot objects', () => {
    const initial={positions:new Map([['a',{x:1,y:2,z:3}]]),pins:new Set(['a']),frozen:true};
    const state=new RendererState(3,'scope',initial);
    state.reconcile(graph,projection);
    state.move('a',{x:40,y:50,z:60});
    state.reconcile(graph,{...projection,nodes:projection.nodes.filter(n=>n.id==='b'),edges:[]});
    state.reconcile(graph,projection);
    expect(state.snapshot().positions.get('a')).toEqual({x:40,y:50,z:60});
    const snapshot=state.snapshot();snapshot.positions.get('a')!.x=900;snapshot.pins.clear();
    expect(state.snapshot().positions.get('a')!.x).toBe(40);
    expect(state.snapshot().pins.has('a')).toBe(true);
    expect(initial.positions.get('a')).toEqual({x:1,y:2,z:3});
    expect(state.move('a',{x:NaN,y:0,z:0})).toBe(false);
    expect(state.move('a',{x:Infinity,y:0,z:0})).toBe(false);
    const replacement=normalizeGraph({nodes:[{id:'b',label:'b',role:'object',properties:{}}],edges:[]});
    state.reconcile(replacement,projectGraph(replacement,createGraphFilters(replacement)));
    expect([...state.snapshot().positions.keys()]).toEqual(['b']);
    expect(state.snapshot().pins.size).toBe(0);
    expect(graph.nodes[0]).not.toHaveProperty('x');
  });
  it('keeps temporary freeze constraints distinct from user pins, including reset and unpin', () => {
    const state = new RendererState(3, 'scope', { positions: new Map(), pins: new Set(), frozen: true });
    state.reconcile(graph, projection);
    const before = state.snapshot();
    state.move('a', { x: 12, y: 34, z: 56 });
    expect(state.snapshot().pins.has('a')).toBe(true);
    expect(state.snapshot().positions.get('b')).toEqual(before.positions.get('b'));
    state.unpinAll();
    expect(state.data.nodes.every(n => n.fx === n.x && n.fy === n.y && n.fz === n.z)).toBe(true);
    state.setFrozen(false);
    expect(state.data.nodes.every(n => n.fx == null && n.fy == null && n.fz == null)).toBe(true);
    state.setFrozen(true);
    state.reset();
    expect(state.snapshot()).toEqual(before);
  });
});
