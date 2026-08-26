import { useState } from 'react';
import { CanvasStage } from './components/CanvasStage';
import { LayerPanel } from './components/LayerPanel';
import { StartScreen } from './components/StartScreen';
import { Toolbar } from './components/Toolbar';
import type { TemplateKind, ToolSettings } from './domain/drawing';
import { useDrawingDocument } from './state/useDrawingDocument';
import { exportPng } from './utils/exportPng';

export default function App() {
  const [started, setStarted] = useState(false);
  const [settings, setSettings] = useState<ToolSettings>({ brush: 'pen', color: '#111111', size: 8 });
  const drawing = useDrawingDocument();

  const start = (template: TemplateKind) => {
    drawing.reset(template);
    setStarted(true);
  };

  if (!started) return <StartScreen onStart={start} />;

  return (
    <div className="app-shell">
      <Toolbar
        settings={settings}
        setSettings={setSettings}
        canUndo={drawing.canUndo}
        canRedo={drawing.canRedo}
        onUndo={drawing.undo}
        onRedo={drawing.redo}
        onSave={() => void exportPng(drawing.document)}
      />
      <div className="workspace">
        <CanvasStage document={drawing.document} settings={settings} onCommitStroke={drawing.commitStroke} />
        <LayerPanel
          layers={drawing.document.layers}
          activeLayerId={drawing.document.activeLayerId}
          onSelect={drawing.selectLayer}
          onAdd={drawing.addLayer}
          onDelete={drawing.deleteActiveLayer}
          onToggle={drawing.toggleLayer}
          onClear={drawing.clearActiveLayer}
        />
      </div>
    </div>
  );
}
