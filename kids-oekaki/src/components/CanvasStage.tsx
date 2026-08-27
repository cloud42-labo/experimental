import { useEffect, useMemo, useRef, useState } from 'react';
import type { DrawingDocument, Point, StampObject, StrokeObject, ToolSettings } from '../domain/drawing';
import { STAMP_SIZE } from '../domain/drawing';
import { renderDocument } from '../engine/renderer';

type Props = {
  document: DrawingDocument;
  settings: ToolSettings;
  onCommitStroke: (stroke: StrokeObject) => void;
  onCommitStamp: (stamp: StampObject) => void;
};

export function CanvasStage({ document, settings, onCommitStroke, onCommitStamp }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const activePointerId = useRef<number | null>(null);
  const [draft, setDraft] = useState<StrokeObject | null>(null);
  const lastPenAt = useRef(0);

  const activeLayer = useMemo(
    () => document.layers.find((layer) => layer.id === document.activeLayerId),
    [document],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    renderDocument(ctx, document, draft);
  }, [document, draft]);

  const pointFromEvent = (event: React.PointerEvent<HTMLCanvasElement>): Point => {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * document.width,
      y: ((event.clientY - rect.top) / rect.height) * document.height,
      pressure: event.pressure > 0 ? event.pressure : 0.5,
    };
  };

  const shouldIgnorePointer = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (event.pointerType === 'pen') {
      lastPenAt.current = performance.now();
      return false;
    }
    if (event.pointerType === 'touch' && performance.now() - lastPenAt.current < 900) return true;
    return !event.isPrimary;
  };

  const start = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (activePointerId.current !== null) return;
    if (shouldIgnorePointer(event) || !activeLayer || activeLayer.locked || !activeLayer.visible) return;
    event.preventDefault();

    if (settings.mode === 'stamp') {
      // スタンプはドラッグ不要。タップした場所にその場で1個置く。
      const point = pointFromEvent(event);
      onCommitStamp({
        id: crypto.randomUUID(),
        type: 'stamp',
        stamp: settings.stampKind,
        x: point.x,
        y: point.y,
        size: STAMP_SIZE,
        color: settings.color,
      });
      return;
    }

    activePointerId.current = event.pointerId;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDraft({
      id: crypto.randomUUID(),
      type: 'stroke',
      brush: settings.brush,
      color: settings.color,
      size: settings.size,
      points: [pointFromEvent(event)],
    });
  };

  const move = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (activePointerId.current !== event.pointerId) return;
    event.preventDefault();
    const coalesced = event.nativeEvent.getCoalescedEvents?.() ?? [event.nativeEvent];
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const points = coalesced.map((raw) => ({
      x: ((raw.clientX - rect.left) / rect.width) * document.width,
      y: ((raw.clientY - rect.top) / rect.height) * document.height,
      pressure: raw.pressure > 0 ? raw.pressure : 0.5,
    }));
    setDraft((current) => current ? { ...current, points: [...current.points, ...points] } : current);
  };

  const stop = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (activePointerId.current !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    activePointerId.current = null;
    if (draft) onCommitStroke(draft);
    setDraft(null);
  };

  return (
    <div className="canvas-area">
      <div className="canvas-frame">
        <canvas
          ref={canvasRef}
          width={document.width}
          height={document.height}
          onPointerDown={start}
          onPointerMove={move}
          onPointerUp={stop}
          onPointerCancel={stop}
          onContextMenu={(event) => event.preventDefault()}
        />
      </div>
    </div>
  );
}
