import { useEffect, useState } from 'react';
import { CanvasStage } from './components/CanvasStage';
import { LayerPanel } from './components/LayerPanel';
import { StartScreen } from './components/StartScreen';
import { Toolbar } from './components/Toolbar';
import type { Orientation, TemplateKind, ToolSettings } from './domain/drawing';
import { useDrawingDocument } from './state/useDrawingDocument';
import type { DrawingHistory } from './state/useDrawingDocument';
import { exportPng } from './utils/exportPng';
import { loadDrawingSession, saveDrawingSession } from './utils/documentStorage';

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

export default function App() {
  const [started, setStarted] = useState(false);
  const [savedHistory, setSavedHistory] = useState<DrawingHistory | null>(null);
  const [storageError, setStorageError] = useState<string>();
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [settings, setSettings] = useState<ToolSettings>({
    mode: 'brush',
    brush: 'pen',
    stampKind: 'heart',
    color: '#111111',
    size: 8,
  });
  const drawing = useDrawingDocument();

  useEffect(() => {
    let cancelled = false;
    void loadDrawingSession()
      .then((session) => {
        if (!cancelled && session) setSavedHistory(session.history);
      })
      .catch((error: unknown) => {
        if (!cancelled) setStorageError(error instanceof Error ? error.message : '保存した作品を読めませんでした');
      });
    return () => { cancelled = true; };
  }, []);

  const saveCurrent = async (showProgress = true) => {
    if (showProgress) setSaveState('saving');
    try {
      const session = await saveDrawingSession(drawing.historySnapshot);
      setSavedHistory(session.history);
      setStorageError(undefined);
      if (showProgress) setSaveState('saved');
    } catch {
      if (showProgress) setSaveState('error');
      setStorageError('ほぞんできませんでした。いまの作品はそのままです。');
    }
  };

  // 描画・レイヤー・Undo/Redoなど作品状態が変わった後、短い間隔を空けて自動保存する。
  // IndexedDBの単一transactionで置き換えるため、失敗時に以前の保存データを途中状態で壊さない。
  useEffect(() => {
    if (!started) return;
    setSaveState((current) => current === 'error' ? current : 'idle');
    const timer = window.setTimeout(() => { void saveCurrent(false); }, 1200);
    return () => window.clearTimeout(timer);
  }, [started, drawing.historySnapshot]);

  const start = (template: TemplateKind, orientation: Orientation) => {
    drawing.reset(template, orientation);
    setSaveState('idle');
    setStarted(true);
  };

  const continueSaved = () => {
    if (!savedHistory) return;
    drawing.restoreHistory(savedHistory);
    setSaveState('saved');
    setStarted(true);
  };

  if (!started) {
    return (
      <StartScreen
        onStart={start}
        onContinue={continueSaved}
        canContinue={Boolean(savedHistory)}
        storageError={storageError}
      />
    );
  }

  return (
    <div className="app-shell">
      <Toolbar
        settings={settings}
        setSettings={setSettings}
        canUndo={drawing.canUndo}
        canRedo={drawing.canRedo}
        onUndo={drawing.undo}
        onRedo={drawing.redo}
        onSaveDraft={() => void saveCurrent(true)}
        onExportPng={() => void exportPng(drawing.document)}
        saveState={saveState}
      />
      {storageError && <div className="save-error-banner" role="alert">⚠️ {storageError}</div>}
      <div className="workspace">
        <CanvasStage
          document={drawing.document}
          settings={settings}
          onCommitStroke={drawing.commitStroke}
          onCommitStamp={drawing.commitStamp}
        />
        <LayerPanel
          layers={drawing.document.layers}
          activeLayerId={drawing.document.activeLayerId}
          onSelect={drawing.selectLayer}
          onAdd={drawing.addLayer}
          onDelete={drawing.deleteActiveLayer}
          onToggle={drawing.toggleLayer}
          onClear={drawing.clearActiveLayer}
          onMove={drawing.moveActiveLayer}
          onOpacityChange={drawing.setActiveLayerOpacity}
        />
      </div>
    </div>
  );
}
