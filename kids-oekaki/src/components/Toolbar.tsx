import type { BrushKind, StampKind, ToolSettings } from '../domain/drawing';

const colors = ['#111111', '#ff4057', '#ff922e', '#ffd43b', '#51cf66', '#22b8cf', '#339af0', '#845ef7', '#a0613b', '#ffffff'];

const brushes: Array<{ key: BrushKind; icon: string; label: string }> = [
  { key: 'pen', icon: '✏️', label: 'ペン' },
  { key: 'marker', icon: '🖍️', label: 'マーカー' },
  { key: 'eraser', icon: '🧽', label: 'けしごむ' },
  { key: 'rainbow', icon: '🌈', label: 'にじいろ' },
  { key: 'neon', icon: '✨', label: 'ネオン' },
];

const stamps: Array<{ key: StampKind; icon: string; label: string }> = [
  { key: 'heart', icon: '💗', label: 'ハート' },
  { key: 'star', icon: '⭐', label: 'ほし' },
  { key: 'speech', icon: '💬', label: 'ふきだし' },
  { key: 'focus', icon: '💥', label: 'しゅうちゅうせん' },
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
  const setColor = (color: string) => setSettings({ ...settings, color, brush: settings.brush === 'eraser' ? 'pen' : settings.brush });
  const saveLabel = saveState === 'saving' ? 'ほぞん中…' : saveState === 'saved' ? 'ほぞん済み' : saveState === 'error' ? 'もう一度ほぞん' : 'ほぞん';

  return (
    <header className="toolbar" aria-label="おえかき どうぐ">
      <div className="tool-section tool-buttons">
        {brushes.map((brush) => (
          <button
            key={brush.key}
            className={settings.mode === 'brush' && settings.brush === brush.key ? 'tool-button active' : 'tool-button'}
            onClick={() => setBrush(brush.key)}
            aria-pressed={settings.mode === 'brush' && settings.brush === brush.key}
          >
            <span aria-hidden="true">{brush.icon}</span><span>{brush.label}</span>
          </button>
        ))}
      </div>

      <div className="tool-section tool-buttons" aria-label="スタンプ">
        {stamps.map((stamp) => (
          <button
            key={stamp.key}
            className={settings.mode === 'stamp' && settings.stampKind === stamp.key ? 'tool-button active' : 'tool-button'}
            onClick={() => setStamp(stamp.key)}
            aria-pressed={settings.mode === 'stamp' && settings.stampKind === stamp.key}
          >
            <span aria-hidden="true">{stamp.icon}</span><span>{stamp.label}</span>
          </button>
        ))}
      </div>

      <div className="tool-section color-row" aria-label="いろ">
        {colors.map((color) => (
          <button
            key={color}
            className={settings.color === color && settings.brush !== 'eraser' ? 'color-dot active' : 'color-dot'}
            style={{ backgroundColor: color }}
            onClick={() => setColor(color)}
            aria-label={`いろ ${color}`}
          />
        ))}
        <label className="custom-color" title="じゆうな いろ">
          🌈
          <input type="color" value={settings.color} onChange={(event) => setColor(event.target.value)} />
        </label>
      </div>

      <label className="tool-section size-control">
        <span>ふとさ <strong>{settings.size}</strong></span>
        <input
          type="range"
          min="1"
          max="60"
          value={settings.size}
          onChange={(event) => setSettings({ ...settings, size: Number(event.target.value) })}
        />
      </label>

      <div className="tool-section action-row">
        <button className="round-action" disabled={!canUndo} onClick={onUndo} aria-label="ひとつ もどる">↶</button>
        <button className="round-action" disabled={!canRedo} onClick={onRedo} aria-label="やりなおす">↷</button>
        <button className="save-button" onClick={onSaveDraft} disabled={saveState === 'saving'}>💾 {saveLabel}</button>
        <button className="export-button" onClick={onExportPng}>🖼️ PNG</button>
      </div>
    </header>
  );
}
