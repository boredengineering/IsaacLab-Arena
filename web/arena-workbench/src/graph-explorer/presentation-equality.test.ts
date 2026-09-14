import { expect, it } from 'vitest';
import { samePresentation } from './presentation-equality';
import type { GraphPresentation } from './renderer-contracts';

const snapshot = (): GraphPresentation => ({ positions: new Map([['a', { x: 1, y: 2, z: 3 }]]), pins: new Set(['a']), frozen: true, camera: { position: { x: 0, y: 0, z: 100 }, target: { x: 0, y: 0, z: 0 } } });
it('compares only numeric presentation content, not freshly allocated container identities', () => {
  expect(samePresentation(snapshot(), snapshot())).toBe(true);
});
it('does not suppress changed positions, pin intent, freeze state or camera', () => {
  const original = snapshot();
  const position = snapshot(); position.positions.get('a')!.x = 2;
  const pins = snapshot(); pins.pins.clear();
  const frozen = snapshot(); frozen.frozen = false;
  const camera = snapshot(); camera.camera!.target!.x = 1;
  for (const changed of [position, pins, frozen, camera]) expect(samePresentation(original, changed)).toBe(false);
});
