import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

// Structural authored-CSS regression for the real 390px/423px overflow proof.
// jsdom cannot measure layout; the isolated authoring browser must verify geometry.
function inspectCss(file: string, check: (rules: CSSRule[]) => void) {
  const style = document.createElement('style');
  style.textContent = readFileSync(`src/${file}`, 'utf8');
  document.head.append(style);
  try {
    check(Array.from(style.sheet!.cssRules));
  } finally {
    style.remove();
  }
}

function declaration(rules: CSSRule[], selector: string, property: string) {
  return (rules.filter(rule => rule.type === CSSRule.STYLE_RULE) as CSSStyleRule[])
    .find(rule => rule.selectorText === selector)?.style.getPropertyValue(property);
}

const fieldset = '.editor-workspace .prompt-section > fieldset';
const select = `${fieldset} select`;

it('lets generation fieldsets shrink below native select min-content width in either editor layout', () => {
  inspectCss('editor.css', rules => {
    expect(declaration(rules, fieldset, 'min-width')).toBe('0');
    expect(declaration(rules, select, 'min-width')).toBe('0');
    expect(declaration(rules, select, 'max-width')).toBe('100%');
    expect(declaration(rules, select, 'min-height')).toBe('38px');
    // Keep natural desktop widths and readable text; do not mask root overflow.
    for (const selector of [fieldset, select]) {
      for (const property of ['width', 'font-size', 'overflow', 'overflow-x']) {
        expect(declaration(rules, selector, property)).toBe('');
      }
    }
  });
});

it('keeps the narrow-screen generation selector a usable touch target', () => {
  inspectCss('editor.css', rules => {
    const mobile = (rules.filter(rule => rule.type === CSSRule.MEDIA_RULE) as CSSMediaRule[])
      .find(rule => rule.conditionText === '(max-width: 760px)');
    expect(mobile).toBeDefined();
    expect(declaration(Array.from(mobile!.cssRules), select, 'min-height')).toBe('44px');
    expect(declaration(Array.from(mobile!.cssRules), 'button', 'min-height')).toBe('44px');
  });
});

it('retains horizontal data scrolling instead of wrapping or shrinking code and tables', () => {
  inspectCss('editor.css', rules => {
    expect(declaration(rules, '.code-editor .cm-scroller', 'overflow')).toBe('auto');
  });
  inspectCss('styles.css', rules => {
    expect(declaration(rules, '.table-scroll', 'overflow-x')).toBe('auto');
  });
  inspectCss('editor-v7.css', rules => {
    const mobile = (rules.filter(rule => rule.type === CSSRule.MEDIA_RULE) as CSSMediaRule[])
      .find(rule => rule.conditionText === '(max-width: 800px)');
    expect(declaration(Array.from(mobile!.cssRules), '.editor-v7 .editor-grid', 'grid-template-columns'))
      .toBe('minmax(0, 1fr)');
  });
});
