import { test, expect } from '@playwright/test';
import { graphLaunchOptions } from './graph-fixtures';
test.use({launchOptions:graphLaunchOptions});
const sample=(page:any)=>page.evaluate(()=>(window as any).rendererRegression.sample());
async function open(page:any,mode='3d'){
  const errors:string[]=[];page.on('pageerror',(e:Error)=>errors.push(e.message));
  await page.goto(`/tests/e2e/renderer-regressions.html?mode=${mode}`);
  await expect.poll(async()=>Boolean((await sample(page)).snapshot)).toBe(true);
  await page.waitForTimeout(600);
  return errors;
}
test('actual 3D engine is idle in React; selection retains DTOs and custom resources have one disposal owner',async({page},testInfo)=>{
  const errors=await open(page);
  const before=await sample(page);
  const gpu=await page.evaluate(()=>(window as any).rendererRegression.gpu());
  if(process.env.WORKBENCH_GRAPH_HARDWARE==='1'){expect(gpu.renderer).not.toMatch(/swiftshader|llvmpipe/i);expect(gpu.vendor).toMatch(/NVIDIA/i);}
  await testInfo.attach('actual-webgl-device',{body:JSON.stringify(gpu),contentType:'application/json'});
  expect(before.resources.length).toBeGreaterThanOrEqual(12);
  expect(before.resources.every((r:any)=>r.disposed===0)).toBe(true);
  await page.waitForTimeout(800);
  const idle=await sample(page);
  expect(idle.commits).toBe(before.commits);
  expect(idle.publications).toBe(before.publications);
  expect(idle.engineFrames).toBeGreaterThan(before.engineFrames);
  await page.getByRole('button',{name:'Select a',exact:true}).click();
  await page.getByRole('button',{name:'Search highlights',exact:true}).click();
  await page.getByRole('button',{name:'Labels',exact:true}).click();
  await page.getByRole('button',{name:'Theme',exact:true}).click();
  await page.waitForTimeout(400);
  const selected=await sample(page);
  expect(selected.dtoReplacements).toBe(before.dtoReplacements);
  expect(selected.nodes).toEqual(before.nodes);
  expect(selected.resources).toEqual(before.resources);
  const projected=await page.evaluate(()=>(window as any).rendererRegression.project());
  const point=projected.find((n:any)=>n.id==='b').ndc;
  await page.mouse.move((point[0]+1)*400,50+(1-point[1])*250);
  await expect(page.getByRole('tooltip')).toContainText('Node b');
  expect((await sample(page)).resources).toEqual(before.resources);
  await page.screenshot({path:testInfo.outputPath('3d-styles-hardware.png')});
  await page.getByRole('button',{name:'Unmount',exact:true}).click();
  await page.waitForTimeout(400);
  const retired=await sample(page);
  expect(retired.publications).toBe(selected.publications);
  expect(retired.resources.every((r:any)=>r.disposed===1)).toBe(true);
  expect(retired.pending).toBe(0);
  expect(retired.errors).toEqual([]);expect(errors).toEqual([]);
  await testInfo.attach('renderer-counters',{body:JSON.stringify({before,idle,selected,retired},null,2),contentType:'application/json'});
});
test('actual live 3D engine settles without an idle parent publication loop',async({page},testInfo)=>{
  const errors=await open(page,'3d&live=1');await page.waitForTimeout(2300);
  const settled=await sample(page);await page.waitForTimeout(800);const idle=await sample(page);
  expect(idle.commits).toBe(settled.commits);expect(idle.publications).toBe(settled.publications);
  expect(idle.nodes).toEqual(settled.nodes);expect(idle.snapshot.frozen).toBe(false);expect(errors).toEqual([]);
  await testInfo.attach('live-idle-counters',{body:JSON.stringify({settled,idle}),contentType:'application/json'});
});
test('actual 2D million-unit fit does not clamp the camera above a useful fit',async({page},testInfo)=>{
  const errors=await open(page,'2d');
  await page.evaluate(()=>{const f=(window as any).rendererRegression;f.move('a',-1e6,-1e6,0);f.move('b',1e6,1e6,0);f.fit();});
  await page.waitForTimeout(300);const fitted=await sample(page);
  expect(fitted.snapshot.camera.zoom).toBeLessThan(0.001);
  expect(errors).toEqual([]);
  await testInfo.attach('2d-fit-range',{body:JSON.stringify(fitted),contentType:'application/json'});
});
test('actual 2D coincident parallel edges use matching visible and hit cubic paths and can be selected',async({page},testInfo)=>{
  const errors=await open(page,'2d&coincident=1');
  await page.mouse.move(350,300);await page.waitForTimeout(200);
  const before=await sample(page);
  for(const id of ['parallel-0','parallel-7']){
    const link=before.links.find((e:any)=>e.id===id);
    const controls=[...link.controls,0,0];
    const visible=before.cubicDraws.find((d:any)=>d.visible&&JSON.stringify(d.controls)===JSON.stringify(controls));
    expect(visible).toBeTruthy();
    expect(before.cubicDraws.some((d:any)=>!d.visible&&JSON.stringify(d.controls)===JSON.stringify(controls))).toBe(true);
    // t=.5 of the actually drawn cubic, safely outside the coincident node disks.
    const x=0.375*(controls[0]+controls[2]),y=0.375*(controls[1]+controls[3]);
    const [a,b,c,d,e,f]=visible.transform;
    const canvas=page.locator('[data-graph-renderer="2d"] canvas');const box=await canvas.boundingBox();
    await page.mouse.click(box!.x+a*x+c*y+e,box!.y+b*x+d*y+f);
    await expect.poll(async()=>(await sample(page)).selection).toEqual({kind:'edge',id});
  }
  expect(errors).toEqual([]);await page.screenshot({path:testInfo.outputPath('coincident-parallel-curves.png')});
  await testInfo.attach('actual-cubic-paths',{body:JSON.stringify(before),contentType:'application/json'});
});
for(const mode of ['2d','3d'])test(`actual ${mode} offscreen rendering pauses RAF and resumes without changing frozen coordinates`,async({page},testInfo)=>{
  const errors=await open(page,mode);const before=await sample(page);
  await page.evaluate(()=>window.scrollTo(0,900));await page.waitForTimeout(300);
  const paused=await sample(page);await page.waitForTimeout(500);const idle=await sample(page);
  expect(paused.pending).toBe(0);expect(idle.engineFrames).toBe(paused.engineFrames);
  await page.evaluate(()=>window.scrollTo(0,0));await page.waitForTimeout(300);
  const resumed=await sample(page);
  expect(resumed.engineFrames).toBeGreaterThan(idle.engineFrames);
  expect(resumed.nodes).toEqual(before.nodes);
  expect(resumed.snapshot.frozen).toBe(true);expect(resumed.snapshot.pins).toEqual(before.snapshot.pins);
  expect(errors).toEqual([]);
  await testInfo.attach('visibility-counters',{body:JSON.stringify({before,paused,idle,resumed},null,2),contentType:'application/json'});
});
test('actual 3D fit and focus accept million-unit endpoints and publish a useful camera',async({page},testInfo)=>{
  const errors=await open(page);
  await page.evaluate(()=>{const f=(window as any).rendererRegression;f.move('a',-1e6,-1e6,-1e6);f.move('b',1e6,1e6,1e6);f.fit();});
  await page.waitForTimeout(300);
  const fitted=await sample(page),projected=await page.evaluate(()=>(window as any).rendererRegression.project());
  for(const n of projected)for(const value of n.ndc)expect(Math.abs(value)).toBeLessThan(1);
  expect(fitted.snapshot.camera.position.z).toBeGreaterThan(1e6);
  expect(fitted.camera.far).toBeGreaterThan(fitted.snapshot.camera.position.z+Math.sqrt(3)*1e6);
  await page.evaluate(()=>(window as any).rendererRegression.focus('b'));await page.waitForTimeout(300);
  const focused=await sample(page);
  for(const coordinate of Object.values(focused.snapshot.camera.target))expect(coordinate).toBeCloseTo(1e6,6);
  expect(focused.snapshot.camera.position.z).toBeGreaterThan(1e6);
  await page.screenshot({path:testInfo.outputPath('3d-million-unit-focus.png')});
  expect(errors).toEqual([]);
  await testInfo.attach('camera-range',{body:JSON.stringify({fitted,projected,focused},null,2),contentType:'application/json'});
});
