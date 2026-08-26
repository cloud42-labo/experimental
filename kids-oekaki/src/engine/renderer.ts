import type { DrawingDocument, DrawingLayer, StrokeObject } from '../domain/drawing';
import { drawTemplate } from '../domain/templates';

const layerSurfaces = new Map<string, HTMLCanvasElement>();

function getLayerSurface(layer: DrawingLayer, width: number, height: number) {
  let surface = layerSurfaces.get(layer.id);
  if (!surface) {
    surface = document.createElement('canvas');
    layerSurfaces.set(layer.id, surface);
  }
  if (surface.width !== width) surface.width = width;
  if (surface.height !== height) surface.height = height;
  return surface;
}

function drawStroke(ctx: CanvasRenderingContext2D, stroke: StrokeObject) {
  if (stroke.points.length === 0) return;

  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.lineWidth = stroke.size;

  if (stroke.brush === 'eraser') {
    ctx.globalCompositeOperation = 'destination-out';
    ctx.globalAlpha = 1;
    ctx.strokeStyle = '#000';
  } else {
    ctx.globalCompositeOperation = 'source-over';
    ctx.strokeStyle = stroke.color;
    ctx.globalAlpha = stroke.brush === 'marker' ? 0.3 : 1;
  }

  if (stroke.points.length === 1) {
    const p = stroke.points[0];
    ctx.beginPath();
    ctx.arc(p.x, p.y, stroke.size / 2, 0, Math.PI * 2);
    ctx.fillStyle = stroke.brush === 'eraser' ? '#000' : stroke.color;
    ctx.fill();
    ctx.restore();
    return;
  }

  ctx.beginPath();
  ctx.moveTo(stroke.points[0].x, stroke.points[0].y);
  for (let i = 1; i < stroke.points.length; i += 1) {
    const p = stroke.points[i];
    ctx.lineTo(p.x, p.y);
  }
  ctx.stroke();
  ctx.restore();
}

function drawStamp(ctx: CanvasRenderingContext2D, object: Extract<DrawingLayer['objects'][number], { type: 'stamp' }>) {
  ctx.save();
  ctx.translate(object.x, object.y);
  ctx.strokeStyle = object.color;
  ctx.fillStyle = object.color;
  ctx.lineWidth = Math.max(4, object.size * 0.08);

  if (object.stamp === 'heart') {
    const s = object.size / 2;
    ctx.beginPath();
    ctx.moveTo(0, s * 0.75);
    ctx.bezierCurveTo(-s * 1.3, 0, -s, -s, 0, -s * 0.3);
    ctx.bezierCurveTo(s, -s, s * 1.3, 0, 0, s * 0.75);
    ctx.fill();
  } else if (object.stamp === 'star') {
    const outer = object.size / 2;
    const inner = outer * 0.45;
    ctx.beginPath();
    for (let i = 0; i < 10; i += 1) {
      const r = i % 2 === 0 ? outer : inner;
      const angle = -Math.PI / 2 + (Math.PI * i) / 5;
      const x = Math.cos(angle) * r;
      const y = Math.sin(angle) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fill();
  } else {
    const w = object.size;
    const h = object.size * 0.65;
    ctx.beginPath();
    ctx.roundRect(-w / 2, -h / 2, w, h, 24);
    ctx.moveTo(w * 0.2, h / 2);
    ctx.lineTo(w * 0.05, h * 0.82);
    ctx.lineTo(-w * 0.02, h / 2);
    ctx.stroke();
  }
  ctx.restore();
}

function renderLayer(ctx: CanvasRenderingContext2D, layer: DrawingLayer) {
  for (const object of layer.objects) {
    if (object.type === 'stroke') drawStroke(ctx, object);
    else drawStamp(ctx, object);
  }
}

export function renderDocument(
  target: CanvasRenderingContext2D,
  document: DrawingDocument,
  draftStroke?: StrokeObject | null,
) {
  target.clearRect(0, 0, document.width, document.height);
  drawTemplate(target, document.template, document.width, document.height);

  for (const layer of document.layers) {
    if (!layer.visible) continue;
    const surface = getLayerSurface(layer, document.width, document.height);
    const ctx = surface.getContext('2d');
    if (!ctx) continue;
    ctx.clearRect(0, 0, document.width, document.height);
    renderLayer(ctx, layer);
    if (draftStroke && layer.id === document.activeLayerId) drawStroke(ctx, draftStroke);
    target.drawImage(surface, 0, 0);
  }
}
