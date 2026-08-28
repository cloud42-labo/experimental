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

type ScreenPoint = { x: number; y: number };

type Viewport = { scale: number; x: number; y: number };

type PinchState = {
  dist0: number;
  mid0: ScreenPoint;
  scale0: number;
  tx0: number;
  ty0: number;
  rectLeft0: number;
  rectTop0: number;
  baseWidth: number;
  baseHeight: number;
};

const MIN_SCALE = 1;
const MAX_SCALE = 4;
const IDENTITY_VIEWPORT: Viewport = { scale: 1, x: 0, y: 0 };

const distance = (a: ScreenPoint, b: ScreenPoint) => Math.hypot(a.x - b.x, a.y - b.y);
const midpoint = (a: ScreenPoint, b: ScreenPoint) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export function CanvasStage({ document, settings, onCommitStroke, onCommitStamp }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const activePointerId = useRef<number | null>(null);
  const [draft, setDraft] = useState<StrokeObject | null>(null);
  const lastPenAt = useRef(0);

  // 2本指ピンチでの拡大・縮小・移動。Documentのデータやcanvasの実解像度は変えず、
  // .canvas-frameへのCSS transformだけで見た目のズームを表現する（PNG書き出しは
  // 別のオフスクリーンcanvasにDocumentから再描画するため影響を受けない）。
  const [viewport, setViewport] = useState<Viewport>(IDENTITY_VIEWPORT);
  const touchPoints = useRef<Map<number, ScreenPoint>>(new Map());
  const pinchRef = useRef<PinchState | null>(null);
  const pendingStampRef = useRef<{ pointerId: number; stamp: StampObject } | null>(null);

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

  // 進行中の1本指ストロークを、コミットせずに破棄する（ピンチ開始時に呼ぶ）。
  const cancelActiveDraw = () => {
    if (activePointerId.current !== null) {
      const canvas = canvasRef.current;
      if (canvas?.hasPointerCapture(activePointerId.current)) {
        canvas.releasePointerCapture(activePointerId.current);
      }
      activePointerId.current = null;
    }
    setDraft(null);
  };

  const cancelPendingStamp = () => {
    pendingStampRef.current = null;
  };

  const beginPinch = () => {
    const frame = frameRef.current;
    const points = Array.from(touchPoints.current.values());
    if (!frame || points.length < 2) return;
    const [p1, p2] = points;
    const rect = frame.getBoundingClientRect();
    pinchRef.current = {
      dist0: Math.max(1, distance(p1, p2)),
      mid0: midpoint(p1, p2),
      scale0: viewport.scale,
      tx0: viewport.x,
      ty0: viewport.y,
      rectLeft0: rect.left,
      rectTop0: rect.top,
      baseWidth: rect.width / viewport.scale,
      baseHeight: rect.height / viewport.scale,
    };
  };

  const updatePinch = () => {
    const pinch = pinchRef.current;
    const points = Array.from(touchPoints.current.values());
    if (!pinch || points.length < 2) return;
    const [p1, p2] = points;
    const dist1 = distance(p1, p2);
    const mid1 = midpoint(p1, p2);
    const newScale = clamp(pinch.scale0 * (dist1 / pinch.dist0), MIN_SCALE, MAX_SCALE);

    // ピンチ開始時に中点の下にあった位置(local座標)を求め、同じ位置が常に
    // 現在の中点の下に来るようtx/tyを解く（拡大中心を2本指の中点に維持する）。
    const localX = (pinch.mid0.x - pinch.rectLeft0) / pinch.scale0;
    const localY = (pinch.mid0.y - pinch.rectTop0) / pinch.scale0;
    let tx = mid1.x - pinch.rectLeft0 + pinch.tx0 - localX * newScale;
    let ty = mid1.y - pinch.rectTop0 + pinch.ty0 - localY * newScale;

    // transform-origin: 0 0（フレーム左上）で拡大しているため、フレーム中心を
    // 動かさない「centered」な状態はtx=0ではなく tx=-maxPanX になる。
    // パン可能範囲は、左端をコンテナ左端に合わせた状態(tx=0)から右端を
    // コンテナ右端に合わせた状態(tx=-2*maxPanX)までの幅2*maxPanXで、
    // これによりMAX_SCALE時にキャンバスの端・角まで過不足なく到達できる。
    // 等倍(scale=1)ではmaxPanX=0となりpanは発生しない。
    const maxPanX = Math.max(0, (pinch.baseWidth * (newScale - 1)) / 2);
    const maxPanY = Math.max(0, (pinch.baseHeight * (newScale - 1)) / 2);
    tx = clamp(tx, -2 * maxPanX, 0);
    ty = clamp(ty, -2 * maxPanY, 0);

    setViewport({ scale: newScale, x: tx, y: ty });
  };

  const endPinch = () => {
    pinchRef.current = null;
  };

  const resetViewport = () => setViewport(IDENTITY_VIEWPORT);

  const start = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (activePointerId.current !== null) return;
    if (shouldIgnorePointer(event) || !activeLayer || activeLayer.locked || !activeLayer.visible) return;
    event.preventDefault();

    if (settings.mode === 'stamp') {
      const point = pointFromEvent(event);
      const stamp: StampObject = {
        id: crypto.randomUUID(),
        type: 'stamp',
        stamp: settings.stampKind,
        x: point.x,
        y: point.y,
        size: STAMP_SIZE,
        color: settings.color,
      };
      if (event.pointerType === 'touch') {
        // タッチはタップ完了(pointerup)まで保留する。指を離す前に2本目が
        // 触れたらピンチ扱いへ切り替わり、このスタンプは作成しない。
        pendingStampRef.current = { pointerId: event.pointerId, stamp };
      } else {
        onCommitStamp(stamp);
      }
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

  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (event.pointerType === 'touch') {
      if (touchPoints.current.size >= 2 && !touchPoints.current.has(event.pointerId)) {
        // 3本目以降の指は無視する（既存2本のピンチはそのまま継続）。
        event.preventDefault();
        return;
      }
      touchPoints.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (touchPoints.current.size === 2) {
        event.preventDefault();
        cancelActiveDraw();
        cancelPendingStamp();
        beginPinch();
        return;
      }
    }
    start(event);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (event.pointerType === 'touch' && touchPoints.current.has(event.pointerId)) {
      touchPoints.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pinchRef.current) {
        event.preventDefault();
        updatePinch();
        return;
      }
    }
    move(event);
  };

  const endTouch = (event: React.PointerEvent<HTMLCanvasElement>, commit: boolean) => {
    if (event.pointerType !== 'touch') return false;
    touchPoints.current.delete(event.pointerId);
    if (pinchRef.current) {
      if (touchPoints.current.size < 2) endPinch();
      return true;
    }
    if (pendingStampRef.current?.pointerId === event.pointerId) {
      const pending = pendingStampRef.current;
      pendingStampRef.current = null;
      if (commit) onCommitStamp(pending.stamp);
      return true;
    }
    return false;
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!endTouch(event, true)) stop(event);
  };

  const handlePointerCancel = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!endTouch(event, false)) stop(event);
  };

  const isZoomed = viewport.scale > 1.001;

  return (
    <div className="canvas-area">
      <div
        ref={frameRef}
        className="canvas-frame"
        style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})`, transformOrigin: '0 0' }}
      >
        <canvas
          ref={canvasRef}
          width={document.width}
          height={document.height}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerCancel}
          onContextMenu={(event) => event.preventDefault()}
        />
      </div>
      {isZoomed && (
        <button
          type="button"
          className="zoom-reset"
          onClick={resetViewport}
          aria-label="ひろさを もとに もどす"
        >
          🔍 {Math.round(viewport.scale * 100)}%
        </button>
      )}
    </div>
  );
}
