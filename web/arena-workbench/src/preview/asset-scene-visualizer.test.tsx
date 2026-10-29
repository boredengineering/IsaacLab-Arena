import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AssetSceneVisualizer, type VisualizerFrame } from './asset-scene-visualizer';

// Synthetic unit-only pixel; production frames are supplied by the parent.
const pixel = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';
const frame: VisualizerFrame = { id: 'cup-front', kind: 'asset', label: 'Cup', camera: 'front', width: 1, height: 1, url: pixel, sha256: 'a'.repeat(64), sourceLabel: 'Historical fixture', captureId: 'capture-1' };
const props = { frames: [frame], draft: 'scene: original', sourceId: 'source-a' };
const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe('offline asset / scene visualizer', () => {
  beforeEach(() => {
    // jsdom has no native modal layout; model only its open/close contract.
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.setAttribute('open', ''); } });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.removeAttribute('open'); } });
    for (const method of ['getItem', 'setItem', 'removeItem', 'clear', 'key'] as const) {
      vi.spyOn(Storage.prototype, method).mockImplementation(() => { throw new Error('Browser storage is forbidden'); });
    }
    vi.stubGlobal('indexedDB', { open: vi.fn(() => { throw new Error('IndexedDB is forbidden'); }) });
  });
  afterEach(() => {
    expect(fetch).not.toHaveBeenCalled();
    expect(XMLHttpRequest.prototype.open).not.toHaveBeenCalled();
    expect(indexedDB.open).not.toHaveBeenCalled();
    for (const method of ['getItem', 'setItem', 'removeItem', 'clear', 'key'] as const) expect(Storage.prototype[method]).not.toHaveBeenCalled();
  });

  it('shows empty catalogues and refuses image URLs that could make network requests', () => {
    const view = render(<AssetSceneVisualizer {...props} frames={[]} />);
    expect(screen.getByText('No historical asset images supplied.')).toBeInTheDocument();
    for (const url of ['', 'https://example.test/image.png', '/api/editor/artifacts/image.png', 'data:image/svg+xml,<svg/>']) {
      view.rerender(<AssetSceneVisualizer {...props} frames={[{ ...frame, url }]} />);
      change('Saved camera', 'front');
      expect(screen.getByRole('alert')).toHaveTextContent('Image unavailable — supply an embedded raster image or local blob URL.');
      expect(screen.queryByRole('img')).not.toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole('tab', { name: 'Scene' }));
    expect(screen.getByText('No historical scene images supplied.')).toBeInTheDocument();
  });

  it('selects exact captures when a subject has multiple saved images at the same camera', () => {
    render(<AssetSceneVisualizer {...props} frames={[frame, { ...frame, id: 'cup-front-2', captureId: 'capture-2', sha256: 'b'.repeat(64) }]} />);
    const capture = screen.getByLabelText('Saved capture') as HTMLSelectElement;
    fireEvent.change(capture, { target: { value: capture.options[1].value } });
    expect(screen.getByTestId('visualizer-frame-metadata')).toHaveTextContent('cup-front-2');
    expect(screen.getByTestId('visualizer-frame-metadata')).toHaveTextContent('capture-2');
  });

  it('retries the same saved image, zooms real pixels, and retires zoom on frame replacement', () => {
    const view = render(<AssetSceneVisualizer {...props} />);
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByRole('alert')).toHaveTextContent('Saved image could not be loaded');
    expect(screen.queryByRole('button', { name: 'Zoom historical image' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry saved image' }));
    fireEvent.load(screen.getByRole('img'));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom historical image' }));
    expect(screen.getByRole('dialog', { name: 'Historical image zoom' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Zoomed historical Cup · front' })).toHaveAttribute('src', pixel);
    fireEvent.error(screen.getByRole('img', { name: 'Zoomed historical Cup · front' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry saved image' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom historical image' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close image' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Zoom historical image' }));
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Zoom historical image' }));
    view.rerender(<AssetSceneVisualizer {...props} frames={[{ ...frame, id: 'replacement', sha256: 'c'.repeat(64) }]} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByTestId('visualizer-frame-metadata')).toHaveTextContent('replacement');
  });
  it.each(['source', 'draft', 'camera', 'resolution'])('freezes a render plan and latches %s changes stale even when values return', (field) => {
    const view = render(<AssetSceneVisualizer {...props} />);
    const review = () => screen.getByRole('button', { name: 'Review render request locally' });
    expect(review()).toBeDisabled();
    fireEvent.click(screen.getByLabelText('I understand this render plan is local only'));
    fireEvent.click(review());
    const frozen = screen.getByTestId('visualizer-render-review').textContent;
    expect(frozen).toContain('scene: original');
    expect(frozen).toContain('source-a');
    expect(frozen).toContain('1024');
    if (field === 'source') view.rerender(<AssetSceneVisualizer {...props} sourceId="source-b" />);
    if (field === 'draft') view.rerender(<AssetSceneVisualizer {...props} draft="scene: edited" />);
    if (field === 'camera') change('Planned camera', 'side');
    if (field === 'resolution') change('Planned resolution', '2048');
    expect(screen.getByText(/Render review is stale/)).toBeInTheDocument();
    expect(screen.getByLabelText('I understand this render plan is local only')).not.toBeChecked();
    view.rerender(<AssetSceneVisualizer {...props} />);
    change('Planned camera', 'isometric');
    change('Planned resolution', '1024');
    expect(screen.getByText(/Render review is stale/)).toBeInTheDocument();
    expect(screen.getByLabelText('I understand this render plan is local only')).not.toBeChecked();
    expect(screen.getByTestId('visualizer-render-review').textContent).toBe(frozen);
    expect(review()).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Clear render review' }));
    expect(screen.queryByTestId('visualizer-render-review')).not.toBeInTheDocument();
    expect(review()).toBeDisabled();
    fireEvent.click(screen.getByLabelText('I understand this render plan is local only'));
    fireEvent.click(review());
    expect(screen.queryByText(/Render review is stale/)).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('clears pending render consent on source changes before any review', () => {
    const view = render(<AssetSceneVisualizer {...props} />);
    fireEvent.click(screen.getByLabelText('I understand this render plan is local only'));
    view.rerender(<AssetSceneVisualizer {...props} sourceId="source-b" />);
    view.rerender(<AssetSceneVisualizer {...props} />);
    expect(screen.getByLabelText('I understand this render plan is local only')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Review render request locally' })).toBeDisabled();
  });

  it.each(['source', 'draft', 'camera', 'resolution', 'intent'])('keeps ovrtx requirements frozen and latches %s changes without enabling Connect', (field) => {
    const view = render(<AssetSceneVisualizer {...props} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Live RTX exploration' }));
    expect(screen.getByText(/ovrtx.*candidate/i)).toBeInTheDocument();
    expect(screen.getByText(/Not live.*no 3D input is streamed/i)).toBeInTheDocument();
    expect(screen.getByText(/Rendering is not physics/)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled();
    for (const intent of ['camera', 'picking', 'edit-proposal', 'view-only']) change('Interaction intent', intent);
    const review = () => screen.getByRole('button', { name: 'Review live requirements locally' });
    expect(review()).toBeDisabled();
    fireEvent.click(screen.getByLabelText('I understand this is requirements review, not connection consent'));
    fireEvent.click(review());
    const frozen = screen.getByTestId('visualizer-live-review').textContent;
    expect(frozen).toContain('source-a');
    expect(frozen).toContain('scene: original');
    expect(frozen).toContain('view-only');
    expect(frozen).toContain('requirements');
    if (field === 'source') view.rerender(<AssetSceneVisualizer {...props} sourceId="source-b" />);
    if (field === 'draft') view.rerender(<AssetSceneVisualizer {...props} draft="scene: changed" />);
    if (field === 'camera') change('Planned camera', 'front');
    if (field === 'resolution') change('Planned resolution', '512');
    if (field === 'intent') change('Interaction intent', 'edit-proposal');
    view.rerender(<AssetSceneVisualizer {...props} />);
    change('Planned camera', 'isometric');
    change('Planned resolution', '1024');
    change('Interaction intent', 'view-only');
    expect(screen.getByText(/Live requirements review is stale/)).toBeInTheDocument();
    expect(screen.getByTestId('visualizer-live-review').textContent).toBe(frozen);
    expect(screen.getByLabelText('I understand this is requirements review, not connection consent')).not.toBeChecked();
    expect(review()).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Assets' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Live RTX exploration' }));
    expect(screen.getByTestId('visualizer-live-review').textContent).toBe(frozen);
    expect(screen.getByText(/Live requirements review is stale/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Clear live requirements review' }));
    expect(screen.queryByTestId('visualizer-live-review')).not.toBeInTheDocument();
    expect(review()).toBeDisabled();
  });

  it('invalidates hidden pending consents and frozen reviews across source changes', () => {
    const view = render(<AssetSceneVisualizer {...props} />);
    fireEvent.click(screen.getByLabelText('I understand this render plan is local only'));
    fireEvent.click(screen.getByRole('button', { name: 'Review render request locally' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Live RTX exploration' }));
    fireEvent.click(screen.getByLabelText('I understand this is requirements review, not connection consent'));
    view.rerender(<AssetSceneVisualizer {...props} sourceId="source-b" />);
    view.rerender(<AssetSceneVisualizer {...props} />);
    expect(screen.getByLabelText('I understand this is requirements review, not connection consent')).not.toBeChecked();
    fireEvent.click(screen.getByRole('tab', { name: 'Assets' }));
    expect(screen.getByText(/Render review is stale/)).toBeInTheDocument();
    expect(screen.getByLabelText('I understand this render plan is local only')).not.toBeChecked();
  });

  it('does not replace an explicitly selected missing capture or subject with other pixels', () => {
    const second = { ...frame, id: 'cup-front-2', captureId: 'capture-2' };
    const plate = { ...frame, id: 'plate', label: 'Plate' };
    const view = render(<AssetSceneVisualizer {...props} frames={[frame, second, plate]} />);
    const captures = screen.getByLabelText('Saved capture') as HTMLSelectElement;
    fireEvent.change(captures, { target: { value: captures.options[1].value } });
    view.rerender(<AssetSceneVisualizer {...props} frames={[frame, plate]} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText(/Selected historical capture is no longer supplied/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Use first available saved capture' }));
    expect(screen.getByRole('img', { name: 'Historical Cup · front' })).toBeInTheDocument();
    change('Saved subject', 'Plate');
    view.rerender(<AssetSceneVisualizer {...props} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText(/No saved front view for Plate/)).toBeInTheDocument();
  });

  it('supports keyboard tab navigation without opening a connection', () => {
    render(<AssetSceneVisualizer {...props} />);
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Assets' }), { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: 'Scene' })).toHaveFocus();
    expect(screen.getByRole('tabpanel')).toHaveAccessibleName('Scene');
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Scene' }), { key: 'End' });
    expect(screen.getByRole('tab', { name: 'Live RTX exploration' })).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Live RTX exploration' }), { key: 'Home' });
    expect(screen.getByRole('tab', { name: 'Assets' })).toHaveFocus();
  });

  it('displays only the exact saved subject, camera and capture; never substitutes missing views', () => {
    render(<AssetSceneVisualizer {...props} frames={[frame, { ...frame, id: 'cup-top', camera: 'top', captureId: 'capture-2' }, { ...frame, id: 'plate', label: 'Plate', camera: 'side' }, { ...frame, id: 'scene', kind: 'scene', label: 'Table scene', camera: 'recorded' }]} />);
    expect(screen.getByRole('img', { name: 'Historical Cup · front' })).toHaveAttribute('src', pixel);
    expect(screen.getByText(/not verified against the current draft/i)).toBeInTheDocument();
    expect(screen.getByTestId('visualizer-frame-metadata')).toHaveTextContent('capture-1');
    expect(screen.getByTestId('visualizer-frame-metadata')).not.toHaveTextContent('base64');
    change('Saved camera', 'top');
    expect(screen.getByRole('img', { name: 'Historical Cup · top' })).toBeInTheDocument();
    expect(screen.getByTestId('visualizer-frame-metadata')).toHaveTextContent('capture-2');
    change('Saved subject', 'Plate');
    expect(screen.getByText(/No saved top view for Plate/)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    change('Saved camera', 'side');
    expect(screen.getByRole('img', { name: 'Historical Plate · side' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Scene' }));
    change('Saved camera', 'recorded');
    expect(screen.getByRole('img', { name: 'Historical Table scene · recorded' })).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});
