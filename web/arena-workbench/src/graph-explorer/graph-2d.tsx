import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph, { type ForceGraphMethods, type NodeObject, type LinkObject } from 'react-force-graph-2d';
import type { SimulationLink as RendererLink, SimulationNode as RendererNode } from './renderer-state';
import type { GraphRendererHandle, GraphRendererProps } from './renderer-contracts';
import { boundedZoom, MIN_LAYOUT_ZOOM, roleColor, selectionHighlight, showLabel } from './renderer-navigation';
import { placeLabel, type LabelBox } from './renderer-labels';
import { emptyLabel, HoverOverlay, observeRendererVisibility, useRendererState, useSurface } from './renderer-react';

/** Canvas adapter: owns only disposable DTOs, layout and camera. */
export default function Graph2D(props: GraphRendererProps) {
  const ref=useRef<ForceGraphMethods<NodeObject<RendererNode>,LinkObject<RendererNode,RendererLink>> | undefined>(undefined);
  const root=useRef<HTMLDivElement>(null);
  const {state,data,latest,frozen,updateFrozen}=useRendererState(props,2);
  const {size,theme}=useSurface(root);
  const [hover,setHover]=useState<{kind:'node'|'edge';id:string;label:string}|null>(null);
  const active=useRef(false);
  const dragging=useRef(false);
  const dragRelease=useRef(0);
  const snapshot=() => {
    const result=state.snapshot(); const engine=ref.current;
    if (engine) {
      const center=engine.centerAt(); const zoom=engine.zoom();
      if ([center.x,center.y,zoom].every(Number.isFinite)) result.camera={center:{x:center.x,y:center.y},zoom};
    }
    return result;
  };
  const publish=() => {if(active.current) latest.current.onSnapshot(snapshot());};
  const refresh=() => {ref.current?.d3ReheatSimulation();publish();};
  const handleRef=useRef<GraphRendererHandle|null>(null);
  useEffect(() => { let cancelled=false; queueMicrotask(()=>{if(!cancelled&&active.current)props.onReady(handleRef.current);});return()=>{cancelled=true;}; },[props.onReady,state]);
  useEffect(() => {
    active.current=true;
    const engine=ref.current;
    if (!engine) return;
    const fit=(ids?:readonly string[]) => {
      const wanted=ids ? new Set(ids) : null;
      if (state.data.nodes.some(n=>!wanted || wanted.has(n.id))) engine.zoomToFit(0,Math.min(120,(root.current?.clientHeight||480)/3),n=>!wanted || wanted.has(n.id));
      publish();
    };
    const handle: GraphRendererHandle = {
      fit,
      zoom(factor) {if(Number.isFinite(factor)&&factor>0){engine.zoom(boundedZoom(engine.zoom()*factor),0);publish();}},
      pan(dx,dy) {if(![dx,dy].every(Number.isFinite))return;const c=engine.centerAt(); const z=engine.zoom(); const x=c.x+dx/z,y=c.y+dy/z;if([x,y].every(v=>Number.isFinite(v)&&Math.abs(v)<=1e6)){engine.centerAt(x,y,0);publish();}},
      orbit() {},
      reset() {state.reset();engine.centerAt(0,0,0);engine.zoom(1,0);refresh();fit();},
      setFrozen(value) {state.setFrozen(value);updateFrozen(value);refresh();},
      setPinned(id,value) {if(latest.current.graph.nodeById.has(id)){state.setPinned(id,value);refresh();}},
      unpinAll() {state.unpinAll();refresh();},
      moveNode(id,position) {if(state.move(id,position))refresh();},
      nudgeNode(id,dx,dy) {const n=state.data.nodes.find(n=>n.id===id);if(n && [dx,dy].every(Number.isFinite) && state.move(id,{x:n.x+dx/engine.zoom(),y:n.y+dy/engine.zoom(),z:0}))refresh();},
      getSnapshot:snapshot,
    };
    const saved=latest.current.snapshot.camera;
    if (saved?.center && [saved.center.x,saved.center.y].every(Number.isFinite)) engine.centerAt(saved.center.x,saved.center.y,0);
    if (saved?.zoom && Number.isFinite(saved.zoom)) engine.zoom(boundedZoom(saved.zoom),0);
    if (!saved) fit();
    handleRef.current=handle;
    const stopVisibility=observeRendererVisibility(root.current,engine);
    return () => {publish();active.current=false;latest.current.onReady(null);stopVisibility();};
  },[state]);
  useEffect(() => {ref.current?.d3ReheatSimulation();},[data,frozen]);
  const highlight=useMemo(()=>selectionHighlight(props.graph,props.selection),[props.graph,props.selection]);
  const emphasized=(n:RendererNode)=>highlight.nodes.has(n.id) || hover?.kind==='node' && hover.id===n.id;
  const selectedEdge=(e:RendererLink)=>highlight.edges.has(e.id) || hover?.kind==='edge' && hover.id===e.id;
  const edgeColor=(e:RendererLink)=>selectedEdge(e)?'#eab308':props.selection?'#94a3b855':theme.edge;
  const shape=(n:RendererNode,ctx:CanvasRenderingContext2D,r:number) => {
    ctx.beginPath();
    if(n.isReifier){ctx.moveTo(n.x,n.y-r*1.3);ctx.lineTo(n.x+r*1.3,n.y);ctx.lineTo(n.x,n.y+r*1.3);ctx.lineTo(n.x-r*1.3,n.y);ctx.closePath();}
    else ctx.arc(n.x,n.y,r,0,2*Math.PI);
  };
  const loop=(e:RendererLink,ctx:CanvasRenderingContext2D) => {
    if(typeof e.source==='string')return false;
    const radius=18+e.laneIndex*8;
    const angle=e.rotation-Math.PI/2;
    const x=e.source.x+Math.cos(angle)*radius,y=e.source.y+Math.sin(angle)*radius;
    ctx.beginPath();ctx.arc(x,y,radius,0,2*Math.PI);return {x,y,radius};
  };
  const label=(text:string,x:number,y:number,ctx:CanvasRenderingContext2D,scale:number) => {
    const font=12/Math.max(scale,0.1);ctx.font=`${font}px system-ui`;const display=text.length>48?`${text.slice(0,47)}…`:text;
    const width=ctx.measureText(display).width;ctx.fillStyle=theme.background;ctx.fillRect(x-width/2-2/scale,y-font,width+4/scale,font*1.4);ctx.fillStyle=theme.text;ctx.textAlign='center';ctx.fillText(display,x,y);
  };
  const nodeLabels=new Map<string,{text:string;x:number;y:number}>();
  const prepareLabels=(ctx:CanvasRenderingContext2D,scale:number)=>{
    nodeLabels.clear();
    const font=12/Math.max(scale,0.1);ctx.font=`${font}px system-ui`;
    const priority=(n:RendererNode)=>(props.selection?.kind==='node'&&props.selection.id===n.id)||(hover?.kind==='node'&&hover.id===n.id);
    const occupied:LabelBox[]=data.nodes.map(n=>({x:n.x-8,y:n.y-8,width:16,height:16}));
    const ordered=[...data.nodes].sort((a,b)=>Number(priority(b))-Number(priority(a)));
    for(const n of ordered){
      if(!showLabel(props.labels,priority(n),scale,data.nodes.length))continue;
      const budget=Math.max(70,Math.min(200,size.width*0.36))/scale;
      let text=n.label.slice(0,48);
      while(text.length>8&&ctx.measureText(text+'…').width>budget)text=text.slice(0,-1);
      if(text.length<n.label.length)text+='…';
      const width=ctx.measureText(text).width+6/scale,height=font*1.4;
      const fallback={x:n.x-width/2,y:n.y+10,width,height};
      const box=priority(n)?fallback:placeLabel(n.x,n.y,width,height,occupied) ?? (props.labels==='all'?fallback:null);
      if(!box)continue;
      occupied.push(box);nodeLabels.set(n.id,{text,x:box.x+width/2,y:box.y+font});
    }
  };
  return <div ref={root} data-graph-renderer="2d" aria-label="2D relationship graph; use table and navigation controls for keyboard access" style={{position:'relative',width:'100%',height:'100%',minHeight:320,minWidth:0,overflow:'hidden'}}>
    <ForceGraph<RendererNode,RendererLink> ref={ref} graphData={data} width={size.width} height={size.height} backgroundColor={theme.background}
      nodeLabel={emptyLabel} linkLabel={emptyLabel} nodeRelSize={7} minZoom={MIN_LAYOUT_ZOOM} maxZoom={20}
      cooldownTicks={frozen?0:120} cooldownTime={frozen?0:2000} autoPauseRedraw={true}
      onRenderFramePre={prepareLabels}
      nodeCanvasObject={(n,ctx,scale)=>{
        ctx.save();ctx.globalAlpha=props.selection&&!emphasized(n)?0.35:1;
        shape(n,ctx,7);ctx.fillStyle=roleColor(n.role);ctx.fill();ctx.strokeStyle=emphasized(n)?'#eab308':theme.text;ctx.lineWidth=(emphasized(n)?3:1)/scale;ctx.stroke();
        if(n.isReifier){ctx.fillStyle=theme.text;ctx.font='bold 8px system-ui';ctx.textAlign='center';ctx.fillText('R',n.x,n.y+3);}
        if(state.pins.has(n.id)){ctx.beginPath();ctx.arc(n.x+7,n.y-7,2/scale,0,Math.PI*2);ctx.fillStyle=theme.text;ctx.fill();}
        const placed=nodeLabels.get(n.id);if(placed)label(placed.text,placed.x,placed.y,ctx,scale);
        ctx.restore();
      }}
      nodePointerAreaPaint={(n,color,ctx)=>{shape(n,ctx,9);ctx.fillStyle=color;ctx.fill();}}
      linkCurvature={e=>e.curvature} linkColor={edgeColor} linkWidth={e=>selectedEdge(e)?2.5:1.2} linkDirectionalArrowLength={e=>e.isLoop?0:5} linkDirectionalArrowRelPos={0.82}
      linkCanvasObjectMode={e=>e.isLoop?'replace':'after'}
      linkCanvasObject={(e,ctx,scale)=>{
        ctx.save();
        if(e.isLoop){const ring=loop(e,ctx);if(ring){ctx.strokeStyle=edgeColor(e);ctx.lineWidth=(selectedEdge(e)?2.5:1.2)/scale;ctx.stroke();const {x,y,radius}=ring;ctx.beginPath();ctx.moveTo(x+radius,y);ctx.lineTo(x+radius-3,y-6);ctx.lineTo(x+radius+3,y-6);ctx.closePath();ctx.fillStyle=edgeColor(e);ctx.fill();if(selectedEdge(e))label(e.label,x,y-radius-4,ctx,scale);}}
        else if(selectedEdge(e)&&typeof e.source!=='string'&&typeof e.target!=='string'){const a=e.source,b=e.target;label(e.label,(a.x+b.x)/2+(b.y-a.y)*e.curvature/2,(a.y+b.y)/2-(b.x-a.x)*e.curvature/2,ctx,scale);}
        ctx.restore();
      }}
      linkPointerAreaPaint={(e,color,ctx,scale)=>{
        if(typeof e.source==='string'||typeof e.target==='string')return;
        if(e.isLoop)loop(e,ctx);
        else {const a=e.source,b=e.target;ctx.beginPath();ctx.moveTo(a.x,a.y);
          // force-graph uses a cubic loop for coincident coordinates, even for distinct IDs.
          if(e.curvature&&a.x===b.x&&a.y===b.y){const d=e.curvature*70;ctx.bezierCurveTo(b.x,b.y-d,b.x+d,b.y,b.x,b.y);}
          else if(e.curvature)ctx.quadraticCurveTo((a.x+b.x)/2+(b.y-a.y)*e.curvature,(a.y+b.y)/2-(b.x-a.x)*e.curvature,b.x,b.y);else ctx.lineTo(b.x,b.y);
        }
        ctx.strokeStyle=color;ctx.lineWidth=10/scale;ctx.stroke();
      }}
      linkHoverPrecision={6} enableNodeDrag enablePointerInteraction enablePanInteraction enableZoomInteraction
      onNodeClick={n=>{if(active.current && !dragging.current && performance.now()-dragRelease.current>150)latest.current.onSelect({kind:'node',id:n.id});}}
      onLinkClick={e=>{if(active.current)latest.current.onSelect({kind:'edge',id:e.id});}} onBackgroundClick={()=>{if(active.current&&performance.now()-dragRelease.current>150)latest.current.onSelect(null);}}
      onNodeHover={n=>setHover(n?{kind:'node',id:n.id,label:`${n.label} · ${n.role} · ${n.id}`} : null)}
      onLinkHover={e=>setHover(e?{kind:'edge',id:e.id,label:`${e.label} · ${e.id}`} : null)}
      onNodeDrag={()=>{dragging.current=true;}}
      onNodeDragEnd={n=>{if(!active.current)return;state.move(n.id,{x:n.x,y:n.y,z:0});dragging.current=false;dragRelease.current=performance.now();refresh();}}
      onZoomEnd={publish} onEngineStop={publish}/>
    <HoverOverlay text={hover?.label??''}/>
  </div>;
}
