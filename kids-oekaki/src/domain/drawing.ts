export const CANVAS_WIDTH = 800;
export const CANVAS_HEIGHT = 1131;

export type TemplateKind = 'blank' | '4koma' | 'diary';
export type BrushKind = 'pen' | 'marker' | 'eraser' | 'rainbow' | 'neon';

export type Point = {
  x: number;
  y: number;
  pressure: number;
};

export type StrokeObject = {
  id: string;
  type: 'stroke';
  brush: BrushKind;
  color: string;
  size: number;
  points: Point[];
};

export type StampObject = {
  id: string;
  type: 'stamp';
  stamp: 'heart' | 'star' | 'speech';
  x: number;
  y: number;
  size: number;
  color: string;
};

export type DrawingObject = StrokeObject | StampObject;

export type DrawingLayer = {
  id: string;
  name: string;
  visible: boolean;
  locked: boolean;
  objects: DrawingObject[];
};

export type DrawingDocument = {
  width: number;
  height: number;
  template: TemplateKind;
  activeLayerId: string;
  layers: DrawingLayer[];
};

export type ToolSettings = {
  brush: BrushKind;
  color: string;
  size: number;
};

const id = () => crypto.randomUUID();

export function createInitialDocument(template: TemplateKind): DrawingDocument {
  const sketchId = id();
  const colorId = id();
  const lineId = id();

  return {
    width: CANVAS_WIDTH,
    height: CANVAS_HEIGHT,
    template,
    activeLayerId: lineId,
    layers: [
      { id: sketchId, name: 'したがき', visible: true, locked: false, objects: [] },
      { id: colorId, name: 'いろぬり', visible: true, locked: false, objects: [] },
      { id: lineId, name: 'せんが', visible: true, locked: false, objects: [] },
    ],
  };
}
