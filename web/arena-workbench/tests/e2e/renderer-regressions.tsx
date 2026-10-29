// Synthetic fixture only. Imports and runs the unmodified production adapters and engines.
import { Profiler, useCallback, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BufferGeometry, Material, Texture, type Mesh, type Object3D, type Camera, Vector3 } from 'three';
import Graph3D from '../../src/graph-explorer/graph-3d';
import Graph2D from '../../src/graph-explorer/graph-2d';
import { RendererState, type SimulationData } from '../../src/graph-explorer/renderer-state';
import { createGraphFilters, normalizeGraph, projectGraph, type GraphSelection } from '../../src/graph-explorer/graph-model';
import type { GraphPresentation, GraphRendererHandle } from '../../src/graph-explorer/renderer-contracts';

const options=new URLSearchParams(location.search);
const observed=new WeakSet<Object3D>();
const cubicDraws=new Map<string,{controls:number[];transform:number[];visible:boolean}>();
const cubic=CanvasRenderingContext2D.prototype.bezierCurveTo;
CanvasRenderingContext2D.prototype.bezierCurveTo=function(...args){const m=this.getTransform(),visible=this.canvas.isConnected;const item={controls:args,transform:[m.a,m.b,m.c,m.d,m.e,m.f],visible};cubicDraws.set(JSON.stringify([args,visible]),item);return cubic.apply(this,args);};
const metrics={selection:null as GraphSelection,camera:null as Camera|null,commits:0,publications:0,dtoReplacements:0,engineFrames:0,pending:new Set<number>(),disposals:{} as Record<string,number>,resources:new Set<string>(),data:null as SimulationData|null,handle:null as GraphRendererHandle|null,errors:[] as string[]};
const reconcile=RendererState.prototype.reconcile;
RendererState.prototype.reconcile=function(...args){const next=reconcile.apply(this,args);if(next!==metrics.data){metrics.dtoReplacements++;metrics.data=next;}return next;};
for(const prototype of [BufferGeometry.prototype,Material.prototype,Texture.prototype]){
  const dispose=prototype.dispose;
  prototype.dispose=function(){metrics.disposals[this.uuid]=(metrics.disposals[this.uuid]??0)+1;return dispose.call(this as never);};
}
const raf=window.requestAnimationFrame.bind(window),cancel=window.cancelAnimationFrame.bind(window);
window.requestAnimationFrame=cb=>{
  const engine=/force.graph/.test(new Error().stack??'');
  const id=raf(time=>{metrics.pending.delete(id);if(engine)metrics.engineFrames++;cb(time);});
  if(engine)metrics.pending.add(id);return id;
};
window.cancelAnimationFrame=id=>{metrics.pending.delete(id);cancel(id);};
function resources(){
  const groups=metrics.data?.nodes.map(n=>(n as unknown as {__threeObj?:Object3D}).__threeObj).filter(Boolean)??[];
  for(const group of groups)group!.traverse(obj=>{
    const mesh=obj as Mesh;
    if(!observed.has(obj)){observed.add(obj);const before=obj.onBeforeRender;obj.onBeforeRender=function(...args){metrics.camera=args[2];before.apply(this,args);};}
    if(mesh.geometry)metrics.resources.add(mesh.geometry.uuid);
    const mats=Array.isArray(mesh.material)?mesh.material:[mesh.material];
    for(const mat of mats)if(mat){metrics.resources.add(mat.uuid);const map=(mat as Material&{map?:Texture}).map;if(map)metrics.resources.add(map.uuid);}
  });
  return [...metrics.resources].map(id=>({id,disposed:metrics.disposals[id]??0}));
}
const graph=normalizeGraph({nodes:['a','b','c'].map(id=>({id,label:`Node ${id}`,role:'object',properties:{}})),edges:options.has('coincident')?Array.from({length:8},(_,i)=>({id:`parallel-${i}`,source:'a',target:'b',label:`parallel ${i}`,properties:{}})):[{id:'ab',source:'a',target:'b',label:'parallel 1',properties:{}},{id:'ab2',source:'a',target:'b',label:'parallel 2',properties:{}},{id:'bc',source:'b',target:'c',label:'link',properties:{}}]});
const initial:GraphPresentation={positions:new Map([['a',{x:-70,y:0,z:0}],['b',{x:70,y:0,z:0}],['c',{x:0,y:80,z:0}]]),pins:new Set(),frozen:!options.has('live')};
if(options.has('coincident')){initial.positions.set('a',{x:0,y:0,z:0});initial.positions.set('b',{x:0,y:0,z:0});}
function Fixture(){
  const [snapshot,setSnapshot]=useState(initial),[selection,setSelection]=useState<GraphSelection>(null),[labels,setLabels]=useState<'selected'|'all'>('selected'),[search,setSearch]=useState(''),[mounted,setMounted]=useState(true);
  const projection=useMemo(()=>projectGraph(graph,{...createGraphFilters(graph),search},selection),[search,selection]);
  const publish=useCallback((next:GraphPresentation)=>{metrics.publications++;setSnapshot(next);},[]);
  const ready=useCallback((handle:GraphRendererHandle|null)=>{metrics.handle=handle;},[]);
  const Renderer=new URLSearchParams(location.search).get('mode')==='2d'?Graph2D:Graph3D;
  return <><nav style={{height:50,position:'sticky',top:0,zIndex:5,background:'white'}}>
    <button onClick={()=>setSelection({kind:'node',id:'a'})}>Select a</button>
    <button onClick={()=>setSelection(null)}>Clear selection</button>
    <button onClick={()=>setSearch('Node')}>Search highlights</button>
    <button onClick={()=>setLabels(x=>x==='all'?'selected':'all')}>Labels</button>
    <button onClick={()=>{document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark';}}>Theme</button>
    <button onClick={()=>setMounted(false)}>Unmount</button>
  </nav><div id="surface" style={{width:800,height:500}}>
    {mounted&&<Profiler id="renderer" onRender={()=>metrics.commits++}><Renderer graph={graph} projection={projection} scopeKey="regressions" snapshot={snapshot} selection={selection} labels={labels} onSelect={value=>{metrics.selection=value;setSelection(value);}} onSnapshot={publish} onReady={ready} onError={message=>metrics.errors.push(message)}/></Profiler>}
  </div><div style={{height:1800}}>Scroll fixture below viewport</div></>;
}
// Test-only introspection; never imported by the application entry point.
(window as any).rendererRegression={
  sample:()=>({selection:metrics.selection,cubicDraws:[...cubicDraws.values()],links:metrics.data?.links.map(e=>({id:e.id,curvature:e.curvature,controls:(e as any).__controlPoints})),commits:metrics.commits,publications:metrics.publications,dtoReplacements:metrics.dtoReplacements,engineFrames:metrics.engineFrames,pending:metrics.pending.size,resources:resources(),errors:metrics.errors,camera:metrics.camera&&{far:(metrics.camera as any).far,fov:(metrics.camera as any).fov,near:(metrics.camera as any).near},snapshot:metrics.handle?.getSnapshot(),nodes:metrics.data?.nodes.map(n=>({id:n.id,x:n.x,y:n.y,z:n.z,fx:n.fx,fy:n.fy,fz:n.fz}))}),
  fit:()=>metrics.handle?.fit(),
  move:(id:string,x:number,y:number,z:number)=>metrics.handle?.moveNode(id,{x,y,z}),
  focus:(id:string)=>metrics.handle?.fit([id]),
  // Observe the actual engine camera passed to custom meshes during WebGL draws.
  project:()=>{const camera=metrics.camera;if(!camera)return null;return metrics.data?.nodes.map(n=>({id:n.id,ndc:new Vector3(n.x,n.y,n.z).project(camera).toArray()}));},
  gpu:()=>{const canvas=document.querySelector('[data-graph-renderer="3d"] canvas') as HTMLCanvasElement;const gl=canvas.getContext('webgl2')!;const info=gl.getExtension('WEBGL_debug_renderer_info')!;return {vendor:gl.getParameter(info.UNMASKED_VENDOR_WEBGL),renderer:gl.getParameter(info.UNMASKED_RENDERER_WEBGL),version:gl.getParameter(gl.VERSION)};},
};
createRoot(document.getElementById('root')!).render(<Fixture/>);
