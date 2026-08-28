import type { BrushKind, StampKind, ToolSettings } from '../domain/drawing';

const brushes: Array<{ key: BrushKind; icon: string; label: string }> = [
  { key: 'pen', icon: '✏️', label: 'ペン' },
  { key: 'marker', icon: '▰', label: 'マーカー' },
  { key: 'eraser', icon: '⌫', label: '消しゴム' },
  { key: 'rainbow', icon: '◐', label: '虹' },
  { key: 'neon', icon: '✦', label: 'ネオン' },
];

const stamps: Array<{ key: StampKind; icon: string; label: string }> = [
  { key: 'heart', icon: '♥', label: 'ハート' },
  { key: 'star', icon: '★', label: '星' },
  { key: 'speech', icon: '□', label: 'ふきだし' },
  { key: 'focus', icon: '✺', label: '集中線' },
];

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

type Props = {
  settings: ToolSettings;
  setSettings: (next: ToolSettings) => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onSaveDraft: () => void;
  onExportPng: () => void;
  saveState: SaveState;
};

export function Toolbar({ settings, setSettings, canUndo, canRedo, onUndo, onRedo, onSaveDraft, onExportPng, saveState }: Props) {
  const setBrush = (brush: BrushKind) => setSettings({ ...settings, mode: 'brush', brush });
  const setStamp = (stampKind: StampKind) => setSettings({ ...settings, mode: 'stamp', stampKind });
  const saveLabel = saveState === 'saving' ? '保存中' : saveState === 'saved' ? '保存済' : saveState === 'error' ? '再保存' : '保存';

  return (
    <header className="toolbar creative-toolbar" aria-label="描画ツール">
      <div className="primary-tools" aria-label="ペンの種類">
        {brushes.map((brush) => (
          <button
            key={brush.key}
            className={settings.mode === 'brush' && settings.brush === brush.key ? 'compact-tool active' : 'compact-tool'}
            onClick={() => setBrush(brush.key)}
            aria-pressed={settings.mode === 'brush' && settings.brush === brush.key}
            title={brush.label}
          >
            <span className="compact-tool-icon" aria-hidden="true">{brush.icon}</span>
            <span className="compact-tool-label">{brush.label}</span>
          </button>
        ))}

        <details className="stamp-menu">
          <summary className={settings.mode === 'stamp' ? 'compact-tool active' : 'compact-tool'} title="スタンプ">
            <span className="compact-tool-icon">◆</span>
            <span className="compact-tool-label">スタンプ</span>
          </summary>
          <div className="stamp-popover">
            {stamps.map((stamp) => (
              <button key={stamp.key} className={settings.mode === 'stamp' && settings.stampKind === stamp.key ? 'active' : ''} onClick={() => setStamp(stamp.key)}>
                <span>{stamp.icon}</span>{stamp.label}
              </button>
            ))}
          </div>
        </details>
      </div>

      <label className="compact-size-control">
        <span>太さ <strong>{settings.size}</strong></span>
        <input
          type="range"
          min="1"
          max="60"
          value={settings.size}
          onChange={(event) => setSettings({ ...settings, size: Number(event.target.value) })}
        />
      </label>

      <div className="toolbar-spacer" />

      <div className="creative-actions">
        <button className="icon-action" disabled={!canUndo} onClick={onUndo} aria-label="ひとつ戻る" title="戻る">↶</button>
        <button className="icon-action" disabled={!canRedo} onClick={onRedo} aria-label="やり直す" title="やり直す">↷</button>
        <button className="text-action primary" onClick={onSaveDraft} disabled={saveState === 'saving'}>⌑ <span>{saveLabel}</span></button>
        <button className="text-action" onClick={onExportPng}>⇩ <span>PNG</span></button>
      </div>
    </header>
  );
}
