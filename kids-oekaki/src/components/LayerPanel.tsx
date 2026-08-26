import type { DrawingLayer } from '../domain/drawing';

type Props = {
  layers: DrawingLayer[];
  activeLayerId: string;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onDelete: () => void;
  onToggle: (id: string) => void;
  onClear: () => void;
};

export function LayerPanel({ layers, activeLayerId, onSelect, onAdd, onDelete, onToggle, onClear }: Props) {
  return (
    <aside className="layer-panel" aria-label="レイヤー">
      <div className="layer-title"><span>📚 レイヤー</span><button onClick={onAdd}>＋</button></div>
      <div className="layer-list">
        {[...layers].reverse().map((layer) => (
          <div key={layer.id} className={layer.id === activeLayerId ? 'layer-row active' : 'layer-row'}>
            <button className="visibility" onClick={() => onToggle(layer.id)} aria-label={layer.visible ? 'かくす' : 'みせる'}>
              {layer.visible ? '👁️' : '🙈'}
            </button>
            <button className="layer-name" onClick={() => onSelect(layer.id)}>{layer.name}</button>
          </div>
        ))}
      </div>
      <div className="layer-actions">
        <button onClick={onClear}>🧹 ぜんぶけす</button>
        <button onClick={onDelete} disabled={layers.length <= 1}>🗑️ けす</button>
      </div>
    </aside>
  );
}
