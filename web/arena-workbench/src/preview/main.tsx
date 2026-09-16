import { createRoot } from 'react-dom/client';
import { PreviewApp } from './preview-app';
import './preview.css';

const root = document.getElementById('preview-root');
if (!root) throw new Error('Preview root missing');
createRoot(root).render(<PreviewApp />);
