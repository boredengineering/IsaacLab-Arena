import { expect, it } from 'vitest';

it('denies WebRTC construction in the offline preview', () => {
 expect(() => new RTCPeerConnection()).toThrow(/forbidden/);
});
it('denies reading or writing browser storage in the offline preview', () => {
 expect(() => localStorage.getItem('example')).toThrow(/forbidden/);
 expect(() => sessionStorage.setItem('example', 'fixture')).toThrow(/forbidden/);
});
