import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { AssetGrid, SnapshotImage } from './snapshots';

it('offers image retry after an artifact fails without starting a render', () => {
  render(<SnapshotImage url="/api/editor/artifacts/cube" label="cube snapshot" />);
  fireEvent.error(screen.getByRole('img', { name: 'cube snapshot' }));
  fireEvent.click(screen.getByRole('button', { name: 'Retry cube snapshot' }));
  expect(screen.getByRole('img', { name: 'cube snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/cube');
});

it('does not request a full-size zoom image until the user opens it', () => {
  render(<SnapshotImage url="/api/editor/artifacts/cube" label="cube snapshot" />);
  expect(screen.queryByAltText('Zoomed cube snapshot')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Zoom cube snapshot' }));
  expect(screen.getByAltText('Zoomed cube snapshot')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Close image' }));
  expect(screen.queryByAltText('Zoomed cube snapshot')).not.toBeInTheDocument();
});

it('explains unsupported robot thumbnails instead of reporting an unrendered asset', () => {
  render(<AssetGrid assets={[{ id: 'robot', role: 'embodiment', properties: {} }]} stale={false} />);
  expect(screen.getByText('Robot preview is included in the scene snapshot.')).toBeInTheDocument();
});

it('loads a thumbnail first with progress and keeps full precision metadata', () => {
  render(<AssetGrid assets={[{ id: 'cube', role: 'object', properties: {} }]} stale={false} receipt={{
    jobId: 'cache', canonicalHash: 'hash', result: {
      warnings: [], scene: null, assets: [{ id: 'cube', artifact_id: 'full', url: '/api/editor/artifacts/full',
        dimensions_m: [1.123456789, 0.0000123, 2], variants: {
          thumbnail: { artifact_id: 'thumb', url: '/api/editor/artifacts/thumb', width: 256, height: 256 },
          full: { artifact_id: 'full', url: '/api/editor/artifacts/full', width: 1024, height: 1024 },
        } }],
    },
  }} />);
  expect(screen.getByRole('img', { name: 'cube snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/thumb');
  expect(screen.getByText('Loading cube snapshot…')).toBeInTheDocument();
  fireEvent.load(screen.getByRole('img', { name: 'cube snapshot' }));
  expect(screen.queryByText('Loading cube snapshot…')).not.toBeInTheDocument();
  expect(screen.getByText('Dimensions (m): 1.123 × 0 × 2')).toHaveAttribute('title', '1.123456789 × 0.0000123 × 2');
  fireEvent.click(screen.getByRole('button', { name: 'Zoom cube snapshot' }));
  expect(screen.getByAltText('Zoomed cube snapshot')).toHaveAttribute('src', '/api/editor/artifacts/full');
});

it('surfaces structured partial failures and renderer timings beside valid images', () => {
  render(<AssetGrid assets={[{ id: 'cube', role: 'object', properties: {} }]} stale={false} receipt={{
    jobId: 'partial', canonicalHash: 'hash', result: { assets: [], scene: null, warnings: [], partial: true,
      errors: [{ id: 'cube', stage: 'framing', code: 'empty_bounds', message: 'No finite bounds' }],
      timings: { render_seconds: 1.23456 },
    },
  }} />);
  expect(screen.getByText('framing · empty_bounds: No finite bounds')).toBeInTheDocument();
  expect(screen.getByText('Partial preview · some artifacts failed')).toBeInTheDocument();
  expect(screen.getByText('render_seconds: 1.235')).toBeInTheDocument();
});

it('never requests untrusted artifact URLs', () => {
  render(<SnapshotImage url="https://untrusted.example/image.png" label="cube snapshot" />);
  expect(screen.getByText('Unsupported artifact URL.')).toBeInTheDocument();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});
