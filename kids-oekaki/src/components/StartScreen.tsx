import type { TemplateKind } from '../domain/drawing';

const templates: Array<{ key: TemplateKind; icon: string; label: string; note: string }> = [
  { key: 'blank', icon: '🖍️', label: 'まっしろ', note: 'じゆうに かこう' },
  { key: '4koma', icon: '💬', label: '4コマまんが', note: 'おはなしを つくろう' },
  { key: 'diary', icon: '📖', label: 'えにっき', note: 'きょうの おもいで' },
];

export function StartScreen({ onStart }: { onStart: (template: TemplateKind) => void }) {
  return (
    <main className="start-screen">
      <div className="start-card">
        <div className="mascot" aria-hidden="true">🎨</div>
        <h1>なにを かく？</h1>
        <p>すきな かみを えらんでね</p>
        <div className="template-grid">
          {templates.map((template) => (
            <button key={template.key} className="template-card" onClick={() => onStart(template.key)}>
              <span className="template-icon" aria-hidden="true">{template.icon}</span>
              <strong>{template.label}</strong>
              <small>{template.note}</small>
            </button>
          ))}
        </div>
      </div>
    </main>
  );
}
