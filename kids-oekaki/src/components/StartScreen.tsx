import { useState } from 'react';
import type { Orientation, TemplateKind } from '../domain/drawing';

const templates: Array<{ key: TemplateKind; icon: string; label: string; note: string }> = [
  { key: 'blank', icon: '🖍️', label: 'まっしろ', note: 'じゆうに かこう' },
  { key: '4koma', icon: '💬', label: '4コマまんが', note: 'おはなしを つくろう' },
  { key: 'diary', icon: '📖', label: 'えにっき', note: 'きょうの おもいで' },
];

const orientations: Array<{ key: Orientation; icon: string; label: string; note: string }> = [
  { key: 'portrait', icon: '📱', label: 'たて', note: 'たてながの かみ' },
  { key: 'landscape', icon: '🖼️', label: 'よこ', note: 'よこながの かみ' },
];

export function StartScreen({ onStart }: { onStart: (template: TemplateKind, orientation: Orientation) => void }) {
  const [template, setTemplate] = useState<TemplateKind | null>(null);

  if (!template) {
    return (
      <main className="start-screen">
        <div className="start-card">
          <div className="mascot" aria-hidden="true">🎨</div>
          <h1>なにを かく？</h1>
          <p>すきな かみを えらんでね</p>
          <div className="template-grid">
            {templates.map((t) => (
              <button key={t.key} className="template-card" onClick={() => setTemplate(t.key)}>
                <span className="template-icon" aria-hidden="true">{t.icon}</span>
                <strong>{t.label}</strong>
                <small>{t.note}</small>
              </button>
            ))}
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="start-screen">
      <div className="start-card">
        <div className="mascot" aria-hidden="true">📐</div>
        <h1>どちらむき？</h1>
        <p>かみの むきを えらんでね</p>
        <div className="template-grid orientation-grid">
          {orientations.map((o) => (
            <button key={o.key} className={`template-card orientation-card orientation-${o.key}`} onClick={() => onStart(template, o.key)}>
              <span className={`orientation-swatch orientation-swatch-${o.key}`} aria-hidden="true" />
              <strong>{o.icon} {o.label}</strong>
              <small>{o.note}</small>
            </button>
          ))}
        </div>
        <button className="back-link" onClick={() => setTemplate(null)}>↩️ かみを えらびなおす</button>
      </div>
    </main>
  );
}
