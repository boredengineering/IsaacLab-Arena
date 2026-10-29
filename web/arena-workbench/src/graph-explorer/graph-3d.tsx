import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph, { type ForceGraphMethods, type NodeObject, type LinkObject } from 'react-force-graph-3d';
import { CanvasTexture, Group, Mesh, MeshLambertMaterial, OctahedronGeometry, SphereGeometry, Sprite, SpriteMaterial } from 'three';
import type { LayoutPosition } from './graph-model';
import type { SimulationLink as RendererLink, SimulationNode as RendererNode } from './renderer-state';
import type { GraphPresentation, GraphRendererHandle, GraphRendererProps } from './renderer-contracts';
import { fitCamera, validCameraPosition, orbitCamera, roleColor, selectionHighlight, translateView, zoomCamera, type Camera3D } from './renderer-navigation';
import { samePresentation } from './presentation-equality';
import { upstreamOwnedResource } from './renderer-resources';
import { emptyLabel, HoverOverlay, observeRendererVisibility, useRendererState, useSurface } from './renderer-react';

interface OrbitControls {
  target: LayoutPosition;
  minDistance: number; maxDistance: number; minPolarAngle: number; maxPolarAngle: number;
  enableDamping: boolean; autoRotate: boolean;
  addEventListener(type: 'end', listener: () => void): void;
  removeEventListener(type: 'end', listener: () => void): void;
}
function controlsOf(value: object): OrbitControls | null {
  if (!('target' in value) || !value.target || typeof value.target !== 'object'
    || !('x' in value.target) || !('y' in value.target) || !('z' in value.target)
    || !('addEventListener' in value) || !('removeEventListener' in value)) return null;
  return value as OrbitControls;
}
const linkCurvature=(e:RendererLink)=>e.curvature;
const linkCurveRotation=(e:RendererLink)=>e.rotation;
interface NodeVisual { group: Group; mesh: Mesh<SphereGeometry | OctahedronGeometry, MeshLambertMaterial>; sprite?: Sprite; texture?: CanvasTexture }

/** Optional WebGL relationship layout. No physical-scene or API ownership. */
export default function Graph3D(props: GraphRendererProps) {
  const ref=useRef<ForceGraphMethods<NodeObject<RendererNode>,LinkObject<RendererNode,RendererLink>> | undefined>(undefined);
  const root=useRef<HTMLDivElement>(null);
  const {state,data,latest,frozen,updateFrozen}=useRendererState(props,3);
  const {size,theme}=useSurface(root);
  const [hover,setHover]=useState<{kind:'node'|'edge';id:string;label:string}|null>(null);
  const active=useRef(false); const dragRelease=useRef(0);
  const visuals=useMemo(()=>new Map<string,NodeVisual>(),[data]);
  const camera=():Camera3D|null => {
    const engine=ref.current;if(!engine)return null;
    const target=controlsOf(engine.controls())?.target;
    const view=engine.camera();const p=view.position;
    // Cover the supported layout cube from the current camera, not the default
    // Three sky radius. Keep the near plane small enough for single-node focus.
    if('far' in view && 'updateProjectionMatrix' in view && typeof view.updateProjectionMatrix==='function'){
      const far=Math.max(2000,Math.hypot(p.x,p.y,p.z)+Math.sqrt(3)*1_000_000+1000);
      if(view.far!==far){view.far=far;view.updateProjectionMatrix();}
    }
    if(!target || !validCameraPosition(target) || !validCameraPosition(p))return null;
    return {position:{x:p.x,y:p.y,z:p.z},target:{x:target.x,y:target.y,z:target.z}};
  };
  const lastCamera=useMemo(()=>({value:undefined as Camera3D|undefined}),[state]);
  const snapshot=()=>{
    const result=state.snapshot();const current=camera();
    if(current)lastCamera.value=current;
    // React may detach the engine ref before passive cleanup. Do not overwrite
    // the last valid camera with an absent camera during retirement publication.
    if(lastCamera.value)result.camera={position:{...lastCamera.value.position},target:{...lastCamera.value.target}};
    return result;
  };
  const published=useRef<{scope:string;value:GraphPresentation}|null>(null);
  const publish=()=>{
    if(!active.current)return;
    const next=snapshot();
    if(published.current?.scope===state.scopeKey&&samePresentation(published.current.value,next))return;
    published.current={scope:state.scopeKey,value:next};latest.current.onSnapshot(next);
  };
  const reheatLayout=()=>{ref.current?.d3ReheatSimulation();publish();};
  const setCamera=(next:Camera3D|null)=>{if(next&&validCameraPosition(next.position)&&validCameraPosition(next.target)){ref.current?.cameraPosition(next.position,next.target,0);publish();}};
  const handleRef=useRef<GraphRendererHandle|null>(null);
  useEffect(()=>{let cancelled=false;queueMicrotask(()=>{if(!cancelled&&active.current)props.onReady(handleRef.current);});return()=>{cancelled=true;};},[props.onReady,state]);
  useEffect(()=>{
    active.current=true;const engine=ref.current;if(!engine)return;
    const controls=controlsOf(engine.controls());
    if(!controls){latest.current.onError('3D orbit controls are unavailable. Switch to 2D or Table.');return;}
    controls.minDistance=10;controls.maxDistance=Infinity;controls.minPolarAngle=0.01;controls.maxPolarAngle=Math.PI-0.01;controls.enableDamping=false;controls.autoRotate=false;
    const fit=(ids?:readonly string[])=>{
      const wanted=ids?new Set(ids):null;const current=camera();if(!current)return;
      const points=state.data.nodes.filter(n=>!wanted||wanted.has(n.id));
      const view=engine.camera();const fov='fov' in view && typeof view.fov==='number'?view.fov:50;
      setCamera(fitCamera(points,current,root.current?.clientWidth||640,root.current?.clientHeight||480,fov));
    };
    const handle:GraphRendererHandle={
      fit,
      zoom(factor){const c=camera();if(c)setCamera(zoomCamera(c,factor));},
      pan(dx,dy){const c=camera();if(!c||![dx,dy].every(Number.isFinite))return;const d=translateView(c,dx,-dy);setCamera({position:{x:c.position.x+d.x,y:c.position.y+d.y,z:c.position.z+d.z},target:{x:c.target.x+d.x,y:c.target.y+d.y,z:c.target.z+d.z}});},
      orbit(yaw,pitch){const c=camera();if(c)setCamera(orbitCamera(c,yaw,pitch));},
      reset(){state.reset();setCamera({position:{x:0,y:0,z:300},target:{x:0,y:0,z:0}});reheatLayout();fit();},
      setFrozen(value){state.setFrozen(value);updateFrozen(value);reheatLayout();},
      setPinned(id,value){if(latest.current.graph.nodeById.has(id)){state.setPinned(id,value);reheatLayout();}},
      unpinAll(){state.unpinAll();reheatLayout();},
      moveNode(id,position){if(state.move(id,position))reheatLayout();},
      nudgeNode(id,dx,dy,dz=0){const c=camera(),n=state.data.nodes.find(n=>n.id===id);if(!c||!n||![dx,dy,dz].every(Number.isFinite))return;const d=translateView(c,dx,-dy,dz);if(state.move(id,{x:n.x+d.x,y:n.y+d.y,z:n.z+d.z}))reheatLayout();},
      getSnapshot:snapshot,
    };
    const saved=latest.current.snapshot.camera;
    if(saved?.position && saved.target && validCameraPosition(saved.position)&&validCameraPosition(saved.target))setCamera({position:saved.position,target:saved.target});else fit();
    const renderer=engine.renderer();renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
    const canvas=renderer.domElement;
    const lost=(event:Event)=>{event.preventDefault();if(active.current){publish();engine.pauseAnimation();latest.current.onError('3D graphics context lost. Switch to 2D or Table.');}};
    const stopVisibility=observeRendererVisibility(root.current,engine);
    canvas.addEventListener('webglcontextlost',lost);controls.addEventListener('end',publish);
    handleRef.current=handle;
    return ()=>{publish();active.current=false;latest.current.onReady(null);canvas.removeEventListener('webglcontextlost',lost);controls.removeEventListener('end',publish);stopVisibility();};
  },[state]);
  // graphData already initializes/reheats the engine asynchronously. Reheating on
  // mount races that initialization and makes three-forcegraph tick an absent layout.
  const previousFrozen=useRef(frozen);
  useEffect(()=>{
    if(previousFrozen.current!==frozen)ref.current?.d3ReheatSimulation();
    previousFrozen.current=frozen;
  },[frozen]);
  // three-forcegraph/three-render-objects recursively dispose custom objects.
  // This map is a styling index, not a resource cache or a second disposal owner.
  const objectFor=useCallback((node:RendererNode)=>{
    const mesh=new Mesh(upstreamOwnedResource(node.isReifier?new OctahedronGeometry(8):new SphereGeometry(6,12,8)),upstreamOwnedResource(new MeshLambertMaterial({color:roleColor(node.role),transparent:true})));
    const group=new Group();group.add(mesh);
    const canvas=document.createElement('canvas');canvas.width=512;canvas.height=64;
    const ctx=canvas.getContext('2d');let sprite:Sprite|undefined,texture:CanvasTexture|undefined;
    if(ctx){ctx.fillStyle='#172033';ctx.fillRect(0,0,512,64);ctx.font='24px system-ui';ctx.fillStyle='#ffffff';ctx.textAlign='center';ctx.fillText(`${node.isReifier?'[R] ':''}${node.label.slice(0,36)}`,256,40);texture=upstreamOwnedResource(new CanvasTexture(canvas));sprite=new Sprite(upstreamOwnedResource(new SpriteMaterial({map:texture,depthTest:false,transparent:true,sizeAttenuation:false})));
      // Sprite normally shares geometry globally; recursive upstream ownership
      // requires a private copy so retiring one node cannot dispose another.
      sprite.geometry=upstreamOwnedResource(sprite.geometry.clone());const pixelScale=2*Math.tan(25*Math.PI/180)/(root.current?.clientHeight||480);sprite.scale.set(256*pixelScale,32*pixelScale,1);sprite.position.set(0,-13,0);sprite.raycast=()=>{};sprite.visible=false;group.add(sprite);}
    visuals.set(node.id,{group,mesh,sprite,texture});return group;
  },[visuals]);
  const highlight=useMemo(()=>selectionHighlight(props.graph,props.selection),[props.graph,props.selection?.kind,props.selection?.id]);
  // Styles and labels update GPU objects without replacing DTOs or restarting layout.
  const styleVisuals=()=>{
    for(const n of data.nodes){const visual=visuals.get(n.id);if(!visual)continue;const priority=highlight.nodes.has(n.id)||hover?.kind==='node'&&hover.id===n.id;
      visual.mesh.material.color.set(priority?'#eab308':roleColor(n.role));visual.mesh.material.opacity=props.selection&&!priority?0.25:1;
      visual.mesh.material.wireframe=state.pins.has(n.id);
      if(visual.sprite){
        visual.sprite.visible=props.labels==='all'||props.selection?.kind==='node'&&props.selection.id===n.id||hover?.kind==='node'&&hover.id===n.id;
        const view=ref.current?.camera();const fov=view&&'fov' in view&&typeof view.fov==='number'?view.fov:50;
        const pixelScale=2*Math.tan(fov*Math.PI/360)/(root.current?.clientHeight||480);
        visual.sprite.scale.set(256*pixelScale,32*pixelScale,1);
      }
    }
  };
  useEffect(()=>{styleVisuals();},[highlight,hover,theme,props.labels,data,size]);
  const hoveredEdge=hover?.kind==='edge'?hover.id:null;const hasSelection=props.selection!==null;
  const edgeColor=useCallback((e:RendererLink)=>highlight.edges.has(e.id)||hoveredEdge===e.id?'#eab308':hasSelection?'#94a3b84d':theme.edge,[highlight,hoveredEdge,hasSelection,theme.edge]);
  const edgeWidth=useCallback((e:RendererLink)=>highlight.edges.has(e.id)?1.8:0.8,[highlight]);
  return <div ref={root} data-graph-renderer="3d" aria-label="3D relationship graph; use table and navigation controls for keyboard access" style={{position:'relative',width:'100%',height:'100%',minHeight:320,minWidth:0,overflow:'hidden'}}>
    <ForceGraph<RendererNode,RendererLink> ref={ref} graphData={data} width={size.width} height={size.height} backgroundColor={theme.background} controlType="orbit" showNavInfo={false}
      nodeLabel={emptyLabel} linkLabel={emptyLabel} nodeThreeObject={objectFor} nodeRelSize={6}
      cooldownTicks={frozen?0:120} cooldownTime={frozen?0:2000} linkCurvature={linkCurvature} linkCurveRotation={linkCurveRotation}
      linkColor={edgeColor} linkWidth={edgeWidth} linkOpacity={0.85} linkDirectionalArrowLength={5} linkDirectionalArrowRelPos={0.8}
      linkDirectionalArrowResolution={6} linkResolution={6} linkHoverPrecision={6} enableNodeDrag enablePointerInteraction enableNavigationControls
      onNodeClick={n=>{if(active.current&&performance.now()-dragRelease.current>150)latest.current.onSelect({kind:'node',id:n.id});}}
      onLinkClick={e=>{if(active.current)latest.current.onSelect({kind:'edge',id:e.id});}} onBackgroundClick={()=>{if(active.current&&performance.now()-dragRelease.current>150)latest.current.onSelect(null);}}
      onNodeHover={n=>setHover(n?{kind:'node',id:n.id,label:`${n.label} · ${n.role} · ${n.id}`} : null)}
      onLinkHover={e=>setHover(e?{kind:'edge',id:e.id,label:`${e.label} · ${e.id}`} : null)}
      onNodeDragEnd={n=>{if(!active.current)return;state.move(n.id,{x:n.x,y:n.y,z:n.z});dragRelease.current=performance.now();styleVisuals();reheatLayout();}}
      onEngineStop={()=>{styleVisuals();publish();}}/>
    <HoverOverlay text={hover?.label??(props.selection?.kind==='edge'?props.graph.edgeById.get(props.selection.id)?.label??'':'')}/>
  </div>;
}
