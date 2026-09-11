import { useEffect, useRef } from 'react';
import { Compartment, EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { tags } from '@lezer/highlight';
import { basicSetup } from 'codemirror';
import { yaml } from '@codemirror/lang-yaml';
import { useTheme } from './theme';

const darkHighlighting = syntaxHighlighting(HighlightStyle.define([
  { tag: tags.comment, color: '#a6b7aa' },
  { tag: [tags.string, tags.special(tags.string)], color: '#b9dba0' },
  { tag: [tags.number, tags.bool, tags.null], color: '#edc785' },
  { tag: [tags.keyword, tags.meta], color: '#c5b4ee' },
  { tag: [tags.propertyName, tags.attributeName], color: '#8dd5b3' },
  { tag: [tags.punctuation, tags.operator], color: '#d0dbd4' },
]));

function editorAppearance(theme: 'light' | 'dark') {
  return [
    EditorView.theme({}, { dark: theme === 'dark' }),
    ...(theme === 'dark' ? [darkHighlighting] : []),
  ];
}
export function CodeEditor({
  value,
  onChange,
  label,
  language = 'yaml',
}: {
  value: string;
  onChange(value: string): void;
  label: string;
  language?: 'yaml' | 'text';
}) {
  const { theme } = useTheme();
  const appearance = useRef(new Compartment());
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const callback = useRef(onChange);
  callback.current = onChange;
  useEffect(() => {
    const editor = new EditorView({
      parent: host.current!,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          appearance.current.of(editorAppearance(theme)),
          ...(language === 'yaml' ? [yaml()] : []),
          EditorView.contentAttributes.of({
            'aria-label': label,
            role: 'textbox',
            'aria-multiline': 'true',
          }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) callback.current(update.state.doc.toString());
          }),
          EditorView.theme({
            '&': { fontSize: '13px' },
            '.cm-scroller': {
              fontFamily: '"SFMono-Regular", Consolas, monospace',
              overflow: 'auto',
            },
            '.cm-content': { padding: '16px 0' },
            '.cm-gutters': { backgroundColor: '#f7f8f7', color: '#79827f', border: 'none' },
            '&.cm-focused': { outline: '2px solid #24816c', outlineOffset: '-2px' },
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
  }, [label, language]);
  useEffect(() => {
    view.current?.dispatch({ effects: appearance.current.reconfigure(editorAppearance(theme)) });
  }, [theme]);
  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value)
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
  }, [value]);
  return <div className={`code-editor ${language}`} ref={host} />;
}
