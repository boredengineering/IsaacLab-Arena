import { expect, it } from 'vitest';
import { placeLabel, type LabelBox } from './renderer-labels';
it('places adaptive labels without overlapping reserved priority labels', () => {
  const occupied:LabelBox[]=[{x:-40,y:10,width:80,height:14}];
  const first=placeLabel(0,0,80,14,occupied)!;
  expect(first.y).toBeLessThan(0);
  expect(occupied).toEqual([{x:-40,y:10,width:80,height:14}]);
  expect(placeLabel(0,0,80,14,[{x:-1000,y:-1000,width:2000,height:2000}])).toBeNull();
});
