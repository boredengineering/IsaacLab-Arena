import scene from './render-samples/scene.png?inline';
import table from './render-samples/table.png?inline';
import cube from './render-samples/cube.png?inline';
import provenance from './render-samples/provenance.json';
import type { VisualizerFrame } from './asset-scene-visualizer';

const images: Record<string, string> = { 'scene.png': scene, 'table.png': table, 'cube.png': cube };

/** Original historical PNG bytes, never a render of the current editor draft. */
export const visualizerFrames: readonly VisualizerFrame[] = provenance.frames.map(frame => ({
 id: frame.id,
 kind: frame.kind as VisualizerFrame['kind'],
 label: frame.label,
 camera: frame.camera as VisualizerFrame['camera'],
 width: frame.width,
 height: frame.height,
 url: images[frame.file],
 sha256: frame.sha256,
 sourceLabel: frame.sourceLabel,
 captureId: frame.captureId,
}));
