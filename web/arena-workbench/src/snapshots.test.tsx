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

it('never requests untrusted artifact URLs', () => {
  render(<SnapshotImage url="https://untrusted.example/image.png" label="cube snapshot" />);
  expect(screen.getByText('Unsupported artifact URL.')).toBeInTheDocument();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});
