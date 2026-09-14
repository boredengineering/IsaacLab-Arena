import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import type { GraphRendererProps } from './renderer-contracts';
import { RendererState } from './renderer-state';

export const emptyLabel = () => '';
export function useRendererState(props: GraphRendererProps, dimensions: 2 | 3) {
  const latest = useRef(props); latest.current = props;
  // A scope change owns a fresh state. Snapshot updates are outputs, not reinitialization requests.
  const state = useMemo(() => new RendererState(dimensions, props.scopeKey, props.snapshot), [dimensions, props.scopeKey]);
  const data = useMemo(() => state.reconcile(props.graph, props.projection), [state, props.graph, props.projection]);
  const [frozen, updateFrozen] = useState(state.frozen);
  useEffect(() => updateFrozen(state.frozen), [state]);
  return {latest,state,data,frozen,updateFrozen};
}
export function useSurface(ref: RefObject<HTMLDivElement | null>) {
  const [size,setSize] = useState({width:640,height:480});
  const [theme,setTheme] = useState({background:'#111827',text:'#f8fafc',edge:'#94a3b8'});
  useEffect(() => {
    const element=ref.current;
    if (!element) return;
    const resize = () => {
      const rect=element.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) setSize(old => old.width === Math.floor(rect.width) && old.height === Math.floor(rect.height) ? old : {width:Math.floor(rect.width),height:Math.floor(rect.height)});
    };
    const colors = () => {
      const style=getComputedStyle(element);
      const text=style.color || '#f8fafc';
      const dark=document.documentElement.dataset.theme === 'dark' || document.documentElement.classList.contains('dark') || getComputedStyle(document.documentElement).colorScheme === 'dark';
      setTheme({background:dark?'#111827':'#f8fafc',text,edge:dark?'#94a3b8':'#64748b'});
    };
    resize(); colors();
    const observer=typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
    observer?.observe(element);
    const themeObserver=new MutationObserver(colors);
    themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:['class','data-theme','style']});
    return () => {observer?.disconnect();themeObserver.disconnect();};
  },[ref]);
  return {size,theme};
}
/** Rendering visibility is independent of force-layout freeze/pin state. */
export function observeRendererVisibility(element: HTMLElement | null, engine: {pauseAnimation(): unknown; resumeAnimation(): unknown}) {
  let live=true;
  let intersecting=typeof IntersectionObserver === 'undefined';
  let running: boolean | undefined;
  const sync=()=>{
    if(!live)return;
    const next=intersecting&&!document.hidden;
    if(next===running)return;
    running=next;
    if(next)engine.resumeAnimation();else engine.pauseAnimation();
  };
  const observer=typeof IntersectionObserver !== 'undefined'?new IntersectionObserver(entries=>{
    intersecting=entries.some(entry=>entry.isIntersecting);sync();
  }):null;
  if(element)observer?.observe(element);
  document.addEventListener('visibilitychange',sync);sync();
  return ()=>{live=false;observer?.disconnect();document.removeEventListener('visibilitychange',sync);engine.pauseAnimation();};
}
export function HoverOverlay({text}: {text:string}) {
  return text ? <div role="tooltip" style={{position:'absolute',left:12,bottom:12,maxWidth:'min(440px,90%)',overflowWrap:'anywhere',whiteSpace:'pre-wrap',padding:'6px 10px',border:'1px solid currentColor',borderRadius:4,background:'var(--panel-bg, #fff)',color:'var(--text, #172033)',pointerEvents:'none',fontSize:12,zIndex:1}}>{text.slice(0,600)}</div> : null;
}
