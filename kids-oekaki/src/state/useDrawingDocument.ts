import { useCallback, useState } from 'react';
import type { DrawingDocument, DrawingLayer, StampObject, StrokeObject, TemplateKind } from '../domain/drawing';
import { createInitialDocument } from '../domain/drawing';

const MAX_HISTORY = 60;

type History = {
  past: DrawingDocument[];
  present: DrawingDocument;
  future: DrawingDocument[];
};

function push(history: History, next: DrawingDocument): History {
  return {
    past: [...history.past, history.present].slice(-MAX_HISTORY),
    present: next,
    future: [],
  };
}

export function useDrawingDocument(initialTemplate: TemplateKind = 'blank') {
  const [history, setHistory] = useState<History>(() => ({
    past: [],
    present: createInitialDocument(initialTemplate),
    future: [],
  }));

  const reset = useCallback((template: TemplateKind) => {
    setHistory({ past: [], present: createInitialDocument(template), future: [] });
  }, []);

  const selectLayer = useCallback((layerId: string) => {
    setHistory((h) => ({ ...h, present: { ...h.present, activeLayerId: layerId } }));
  }, []);

  const commitStroke = useCallback((stroke: StrokeObject) => {
    setHistory((h) => {
      const active = h.present.layers.find((layer) => layer.id === h.present.activeLayerId);
      if (!active || active.locked || !active.visible) return h;
      const layers = h.present.layers.map((layer) =>
        layer.id === h.present.activeLayerId ? { ...layer, objects: [...layer.objects, stroke] } : layer,
      );
      return push(h, { ...h.present, layers });
    });
  }, []);

  const commitStamp = useCallback((stamp: StampObject) => {
    setHistory((h) => {
      const active = h.present.layers.find((layer) => layer.id === h.present.activeLayerId);
      if (!active || active.locked || !active.visible) return h;
      const layers = h.present.layers.map((layer) =>
        layer.id === h.present.activeLayerId ? { ...layer, objects: [...layer.objects, stamp] } : layer,
      );
      return push(h, { ...h.present, layers });
    });
  }, []);

  const addLayer = useCallback(() => {
    setHistory((h) => {
      const layer: DrawingLayer = {
        id: crypto.randomUUID(),
        name: `レイヤー${h.present.layers.length + 1}`,
        visible: true,
        locked: false,
        objects: [],
      };
      return push(h, {
        ...h.present,
        layers: [...h.present.layers, layer],
        activeLayerId: layer.id,
      });
    });
  }, []);

  const deleteActiveLayer = useCallback(() => {
    setHistory((h) => {
      if (h.present.layers.length <= 1) return h;
      const index = h.present.layers.findIndex((layer) => layer.id === h.present.activeLayerId);
      const layers = h.present.layers.filter((layer) => layer.id !== h.present.activeLayerId);
      const next = layers[Math.min(Math.max(index - 1, 0), layers.length - 1)];
      return push(h, { ...h.present, layers, activeLayerId: next.id });
    });
  }, []);

  const clearActiveLayer = useCallback(() => {
    setHistory((h) => {
      const active = h.present.layers.find((layer) => layer.id === h.present.activeLayerId);
      if (!active || active.objects.length === 0) return h;
      const layers = h.present.layers.map((layer) =>
        layer.id === h.present.activeLayerId ? { ...layer, objects: [] } : layer,
      );
      return push(h, { ...h.present, layers });
    });
  }, []);

  const toggleLayer = useCallback((layerId: string) => {
    setHistory((h) => {
      const layers = h.present.layers.map((layer) =>
        layer.id === layerId ? { ...layer, visible: !layer.visible } : layer,
      );
      return push(h, { ...h.present, layers });
    });
  }, []);

  const undo = useCallback(() => {
    setHistory((h) => {
      if (!h.past.length) return h;
      const previous = h.past[h.past.length - 1];
      return { past: h.past.slice(0, -1), present: previous, future: [h.present, ...h.future] };
    });
  }, []);

  const redo = useCallback(() => {
    setHistory((h) => {
      if (!h.future.length) return h;
      const next = h.future[0];
      return {
        past: [...h.past, h.present].slice(-MAX_HISTORY),
        present: next,
        future: h.future.slice(1),
      };
    });
  }, []);

  return {
    document: history.present,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
    reset,
    selectLayer,
    commitStroke,
    commitStamp,
    addLayer,
    deleteActiveLayer,
    clearActiveLayer,
    toggleLayer,
    undo,
    redo,
  };
}
