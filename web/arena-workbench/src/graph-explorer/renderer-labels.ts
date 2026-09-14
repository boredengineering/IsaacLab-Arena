export interface LabelBox { x: number; y: number; width: number; height: number }
/** Reserve priority labels first; omit auto labels if every nearby slot is occupied. */
export function placeLabel(x: number, y: number, width: number, height: number, occupied: readonly LabelBox[]): LabelBox | null {
  const gap=10;
  const candidates=[
    {x:x-width/2,y:y+gap,width,height},
    {x:x-width/2,y:y-gap-height,width,height},
    {x:x+gap,y:y-height/2,width,height},
    {x:x-gap-width,y:y-height/2,width,height},
    {x:x-width/2,y:y+gap+height+4,width,height},
  ];
  return candidates.find(a=>occupied.every(b=>a.x+a.width+2<b.x || b.x+b.width+2<a.x || a.y+a.height+2<b.y || b.y+b.height+2<a.y)) ?? null;
}
