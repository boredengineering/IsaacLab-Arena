import { expect, it } from 'vitest';
import { cameraBasis, orbitCamera, zoomCamera, translateView, selectionHighlight, showLabel, roleColor, fitCamera } from './renderer-navigation';
import { normalizeGraph } from './graph-model';
it('fits the entire accepted million-unit layout range, with no artificial distance cap',()=>{
  const camera={position:{x:0,y:0,z:300},target:{x:0,y:0,z:0}};
  for(const [width,height] of [[900,480],[320,900]]){
    const points=[{x:-1e6,y:-1e6,z:-1e6},{x:1e6,y:1e6,z:1e6}];
    const fit=fitCamera(points,camera,width,height,50)!;
    const distance=Math.hypot(fit.position.x,fit.position.y,fit.position.z);
    const halfFov=Math.min(25*Math.PI/180,Math.atan(Math.tan(25*Math.PI/180)*width/height));
    expect(distance*Math.sin(halfFov)).toBeGreaterThan(Math.sqrt(3)*1e6+35);
    expect(zoomCamera(fit,1)).toEqual(fit);
    expect(orbitCamera(fit,0,0)).not.toBeNull();
  }
  const focus=fitCamera([{x:1e6,y:1e6,z:1e6}],camera,900,480,50)!;
  expect(focus.position.z).toBeGreaterThan(1e6);
  expect(zoomCamera(focus,1)).toEqual(focus);
});
it('fits an off-origin visible subset around its actual center, including a single node', () => {
  const c={position:{x:0,y:0,z:300},target:{x:0,y:0,z:0}};
  const fit=fitCamera([{x:2000,y:400,z:100}],c,900,480,50)!;
  expect(fit.target).toEqual({x:2000,y:400,z:100});
  expect(fit.position.z).toBeGreaterThan(100);
  expect(fitCamera([],c,900,480,50)).toBeNull();
});
it('bounds camera motion and uses view-relative axes without singularities', () => {
  const camera = { position: { x: 100, y: 0, z: 0 }, target: { x: 0, y: 0, z: 0 } };
  expect(cameraBasis(camera).right).toEqual({ x: 0, y: 0, z: -1 });
  expect(translateView(camera, 10, 0, 0)).toEqual({ x: 0, y: 0, z: -10 });
  expect(zoomCamera(camera, Infinity)).toBeNull();
  expect(orbitCamera(camera, NaN, 0)).toBeNull();
  const orbited = orbitCamera(camera, 0, 100)!;
  expect(Object.values(orbited.position).every(Number.isFinite)).toBe(true);
  expect(Math.hypot(orbited.position.x, orbited.position.z)).toBeGreaterThan(0);
  expect(zoomCamera(camera, 1e100)!.position.x).toBeGreaterThanOrEqual(10);
  expect(camera.position.x).toBe(100);
});
it('highlights exact selected edges or a node neighborhood and prioritizes labels', () => {
  const graph = normalizeGraph({ nodes: ['a','b','c'].map(id => ({id, label:id, role:'object',properties:{}})), edges: [{id:'ab',source:'a',target:'b',label:'r',properties:{}},{id:'bc',source:'b',target:'c',label:'r',properties:{}}] });
  expect([...selectionHighlight(graph, {kind:'edge',id:'ab'}).edges]).toEqual(['ab']);
  expect([...selectionHighlight(graph, {kind:'node',id:'b'}).nodes].sort()).toEqual(['a','b','c']);
  expect(showLabel('auto', false, 0.1, 256)).toBe(false);
  expect(showLabel('selected', true, 0.1, 256)).toBe(true);
  expect(roleColor('object')).toBe(roleColor('object'));
});
