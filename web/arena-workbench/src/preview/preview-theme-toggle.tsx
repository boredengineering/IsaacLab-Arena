/** Original dashboard switch presentation, with preview-local state only. */
export function PreviewThemeToggle({ theme, onToggle }: { theme: 'light' | 'dark'; onToggle(): void }) {
 return <button type="button" className="preview-theme-toggle" role="switch" aria-label="Dark mode" aria-checked={theme === 'dark'} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} onClick={onToggle}>
  <svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
   {theme === 'dark' ? <path d="M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z" /> : <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>}
  </svg>
  <span>{theme === 'dark' ? 'Dark' : 'Light'}</span>
  <span className="preview-theme-track" aria-hidden="true"><span /></span>
 </button>;
}
