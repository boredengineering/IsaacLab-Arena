import { render, waitFor, act, cleanup } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { createGraphFilters, normalizeGraph, projectGraph } from './graph-model';
import type { GraphRendererHandle, GraphRendererProps } from './renderer-contracts';
const captured = vi.hoisted(() => ({ props: {} as Record<string, unknown> }));
vi.mock('react-force-graph-2d', () => ({ default: (props: Record<string, unknown>) => {
  captured.props = props;
  const ref = props.ref as {current: unknown};
  ref.current = { centerAt: () => ({x:0,y:0}), zoom: () => 1, zoomToFit: vi.fn(), d3ReheatSimulation: vi.fn(), pauseAnimation: vi.fn(), resumeAnimation: vi.fn() };
  return <canvas />;
} }));
vi.mock('react-force-graph-3d', () => ({ default: (props: Record<string, unknown>) => {
  captured.props = props;
  const ref = props.ref as {current: unknown};
  const position = {x:0,y:0,z:300};
  ref.current = { camera: () => ({position,far:2000,updateProjectionMatrix:vi.fn()}), controls: () => ({target:{x:0,y:0,z:0},addEventListener:vi.fn(),removeEventListener:vi.fn(),update:vi.fn()}), renderer: () => ({domElement:document.createElement('canvas'),setPixelRatio:vi.fn()}),cameraPosition:vi.fn(),refresh:vi.fn(),zoomToFit:vi.fn(), d3ReheatSimulation:vi.fn(),pauseAnimation:vi.fn(),resumeAnimation:vi.fn() };
  return <canvas/>;
} }));
import Graph2D from './graph-2d';
import Graph3D from './graph-3d';
it('3D exposes isolated numeric camera and layout snapshots with frozen manipulation', async () => {
  const graph=normalizeGraph({nodes:[{id:'a',label:'a',role:'reifier',properties:{}}],edges:[]});
  let handle: GraphRendererHandle | null=null;
  const view=render(<Graph3D graph={graph} projection={projectGraph(graph,createGraphFilters(graph))} scopeKey="3" snapshot={{positions:new Map(),pins:new Set(),frozen:true}} selection={null} labels="selected" onSelect={vi.fn()} onReady={h=>{handle=h;}} onSnapshot={vi.fn()} onError={vi.fn()}/>);
  await waitFor(()=>expect(handle).not.toBeNull());
  expect(handle!.getSnapshot().camera?.position).toEqual({x:0,y:0,z:300});
  act(()=>handle!.nudgeNode('a',10,0));
  expect(handle!.getSnapshot().pins.has('a')).toBe(true);
  act(()=>handle!.reset());
  expect(handle!.getSnapshot().frozen).toBe(true);
  expect(handle!.getSnapshot().pins.size).toBe(0);
  view.unmount();
  expect(handle).toBeNull();
});
afterEach(cleanup);
function rendererProps(): GraphRendererProps {
  const graph=normalizeGraph({nodes:['a','b'].map(id=>({id,label:id,role:'object',properties:{}})),edges:[{id:'ab',source:'a',target:'b',label:'r',properties:{}}]});
  return {graph,projection:projectGraph(graph,createGraphFilters(graph)),scopeKey:'regression',snapshot:{positions:new Map(),pins:new Set(),frozen:true},selection:null,labels:'selected',onSelect:vi.fn(),onReady:vi.fn(),onSnapshot:vi.fn(),onError:vi.fn()};
}
it('3D idle snapshot rerenders retain update accessors and publish only changed snapshots', async () => {
  const props=rendererProps(); const view=render(<Graph3D {...props}/>);
  await waitFor(()=>expect(props.onReady).toHaveBeenCalled());
  const before={...captured.props};
  act(()=>(captured.props.onEngineStop as ()=>void)());
  const count=vi.mocked(props.onSnapshot).mock.calls.length;
  act(()=>(captured.props.onEngineStop as ()=>void)());
  expect(vi.mocked(props.onSnapshot).mock.calls.length).toBe(count);
  view.rerender(<Graph3D {...props} snapshot={{...props.snapshot}}/>);
  for(const key of ['graphData','nodeThreeObject','linkCurvature','linkCurveRotation','linkColor','linkWidth'])expect(captured.props[key],key).toBe(before[key]);
  view.rerender(<Graph3D {...props} selection={{kind:'node',id:'a'}}/>);
  const selected={...captured.props};
  view.rerender(<Graph3D {...props} selection={{kind:'node',id:'a'}}/>);
  expect(captured.props.linkColor).toBe(selected.linkColor);
  expect(captured.props.linkWidth).toBe(selected.linkWidth);
});
it('3D never flushes custom resources for hover, labels, theme or layout commands; upstream owns disposal', async () => {
  const canvas=vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(null);
  const props=rendererProps(); const view=render(<Graph3D {...props}/>);
  await waitFor(()=>expect(props.onReady).toHaveBeenCalled());
  const engine=(captured.props.ref as {current:{refresh:ReturnType<typeof vi.fn>}}).current;
  expect(engine.refresh).not.toHaveBeenCalled();
  const factory=captured.props.nodeThreeObject as (n:unknown)=>import('three').Group;
  const node=(captured.props.graphData as {nodes:unknown[]}).nodes[0];
  const group=factory(node);const mesh=group.children[0] as import('three').Mesh;
  const dispose=vi.spyOn(mesh.geometry,'dispose');
  act(()=>(captured.props.onNodeHover as (n:unknown)=>void)(node));
  view.rerender(<Graph3D {...props} labels="all"/>);
  expect(dispose).not.toHaveBeenCalled();
  // Reconstruction is upstream-owned: a later factory call must never recycle a retired group.
  mesh.geometry.dispose();
  expect(factory(node)).not.toBe(group);
  view.unmount();await act(async()=>{});
  expect(dispose).toHaveBeenCalledTimes(1);
  canvas.mockRestore();
});
it('2D coincident distinct parallel endpoints paint the same cubic hit loop as upstream visible geometry', () => {
  const props=rendererProps();render(<Graph2D {...props}/>);
  const data=captured.props.graphData as {nodes:Record<string,unknown>[];links:Record<string,unknown>[]};
  const [a,b]=data.nodes;Object.assign(a,{x:20,y:30});Object.assign(b,{x:20,y:30});
  const paint=captured.props.linkPointerAreaPaint as (e:unknown,c:string,ctx:unknown,scale:number)=>void;
  const ctx={beginPath:vi.fn(),moveTo:vi.fn(),quadraticCurveTo:vi.fn(),bezierCurveTo:vi.fn(),stroke:vi.fn()};
  for(const curvature of [-0.3,0.3]){
    paint({...data.links[0],source:a,target:b,curvature,isLoop:false},'#123456',ctx,1);
    expect(ctx.bezierCurveTo).toHaveBeenLastCalledWith(20,30-curvature*70,20+curvature*70,30,20,30);
  }
  expect(ctx.quadraticCurveTo).not.toHaveBeenCalled();
});
it('exposes a real contract handle and never passes HTML labels or source properties to the engine', async () => {
  const graph = normalizeGraph({ nodes: [{id:'a',label:'<img src=x>',role:'reifier',properties:{secret:'not-for-engine'}}],edges:[] });
  let handle: GraphRendererHandle | null = null;
  const onSnapshot = vi.fn(); const onSelect = vi.fn();
  const props: GraphRendererProps = { graph, projection:projectGraph(graph,createGraphFilters(graph)), scopeKey:'s',snapshot:{positions:new Map(),pins:new Set(),frozen:true},selection:null, labels:'auto', onReady:h=>{handle=h;},onSnapshot,onSelect,onError:vi.fn() };
  const view = render(<Graph2D {...props}/>);
  await waitFor(() => expect(handle).not.toBeNull());
  expect((captured.props.nodeLabel as () => string)()).toBe('');
  expect((captured.props.linkLabel as () => string)()).toBe('');
  const data = captured.props.graphData as {nodes: {id:string;properties?:unknown}[]};
  expect(data.nodes[0].properties).toBeUndefined();
  act(() => handle!.moveNode('a',{x:10,y:20,z:0}));
  expect(handle!.getSnapshot().pins.has('a')).toBe(true);
  act(() => handle!.unpinAll());
  expect(handle!.getSnapshot().frozen).toBe(true);
  expect(handle!.getSnapshot().pins.size).toBe(0);
  expect(captured.props.cooldownTicks).toBe(0);
  act(() => (captured.props.onNodeClick as (n:{id:string})=>void)(data.nodes[0]));
  expect(onSelect).toHaveBeenCalledWith({kind:'node',id:'a'});
  view.unmount();
  expect(handle).toBeNull();
  expect(onSnapshot).toHaveBeenCalled();
});
