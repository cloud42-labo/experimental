import { useEffect, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { CanvasStage } from './components/CanvasStage';
import { ColorPalette } from './components/ColorPalette';
import { LayerPanel } from './components/LayerPanel';
import { StartScreen } from './components/StartScreen';
import { Toolbar } from './components/Toolbar';
import type { Orientation, TemplateKind, ToolSettings } from './domain/drawing';
import { useDrawingDocument } from './state/useDrawingDocument';
import type { DrawingHistory } from './state/useDrawingDocument';
import { exportPng } from './utils/exportPng';
import { loadDrawingSession, saveDrawingSession } from './utils/documentStorage';
import './save-resume.css';
import './creative-ui.css';

type SaveState = 'idle' | 'saving' | 'saved' | 'error';
const RECENT_COLORS_KEY = 'kids-oekaki-recent-colors';

function componentHex(value: number) {
  return Math.max(0, Math.min(255, value)).toString(16).padStart(2, '0');
}

export default function App() {
  const [started, setStarted] = useState(false);
  const [savedHistory, setSavedHistory] = useState<DrawingHistory | null>(null);
  const [storageError, setStorageError] = useState<string>();
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [recentColors, setRecentColors] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(RECENT_COLORS_KEY) ?? '[]');
      return Array.isArray(stored) ? stored.filter((value): value is string => typeof value === 'string').slice(0, 8) : [];
    } catch {
      return [];
    }
  });
  const [settings, setSettings] = useState<ToolSettings>({
    mode: 'brush',
    brush: 'pen',
    stampKind: 'heart',
    color: '#111111',
    size: 8,
  });
  const drawing = useDrawingDocument();

  useEffect(() => {
    try { localStorage.setItem(RECENT_COLORS_KEY, JSON.stringify(recentColors)); } catch { /* localStorage is optional */ }
  }, [recentColors]);

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
      setStorageError('保存できませんでした。いまの作品はそのままです。');
    }
  };

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

  const applyColor = (color: string) => {
    const next = color.toLowerCase();
    setSettings((current) => ({
      ...current,
      color: next,
      mode: current.mode === 'eyedropper' ? 'brush' : current.mode,
      brush: current.brush === 'eraser' ? 'pen' : current.brush,
    }));
    setRecentColors((current) => [next, ...current.filter((item) => item.toLowerCase() !== next)].slice(0, 8));
  };

  const handleColorPick = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (settings.mode !== 'eyedropper') return;
    const target = event.target;
    if (!(target instanceof HTMLCanvasElement)) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = target.getBoundingClientRect();
    const x = Math.max(0, Math.min(target.width - 1, Math.floor(((event.clientX - rect.left) / rect.width) * target.width)));
    const y = Math.max(0, Math.min(target.height - 1, Math.floor(((event.clientY - rect.top) / rect.height) * target.height)));
    const ctx = target.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;
    const pixel = ctx.getImageData(x, y, 1, 1).data;
    const picked = pixel[3] === 0 ? '#ffffff' : `#${componentHex(pixel[0])}${componentHex(pixel[1])}${componentHex(pixel[2])}`;
    applyColor(picked);
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
    <div className="app-shell creative-shell">
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
      <div className="workspace creative-workspace" onPointerDownCapture={handleColorPick}>
        <ColorPalette
          color={settings.color}
          recentColors={recentColors}
          eyedropperActive={settings.mode === 'eyedropper'}
          onColorChange={applyColor}
          onEyedropper={() => setSettings((current) => ({ ...current, mode: current.mode === 'eyedropper' ? 'brush' : 'eyedropper' }))}
        />
        <CanvasStage
          document={drawing.document}
          settings={settings}
          onCommitStroke={drawing.commitStroke}
          onCommitBlur={drawing.commitBlur}
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
