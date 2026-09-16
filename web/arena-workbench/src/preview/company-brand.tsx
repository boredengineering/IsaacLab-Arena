import wordmark from './brand/wordmark.json';
import notices from './brand/THIRD_PARTY_NOTICES.txt?raw';

/** Path-only reproduction of the company's public website wordmark. */
export function CompanyWordmark() {
  return <svg className="preview-wordmark" role="img" aria-label="Cybernetic-Physics" viewBox={wordmark.viewBox} fill="currentColor" focusable="false">
    <title>Cybernetic-Physics</title>
    {wordmark.paths.map((path, index) => <path key={index} d={path} />)}
  </svg>;
}

/** Keep font attribution with the single-file offline distribution. */
export function TypographyLicenses() {
  return <details className="preview-font-notices"><summary>Typography licenses</summary><pre>{notices}</pre></details>;
}
