import type { DrawingHistory } from '../state/useDrawingDocument';

const DB_NAME = 'kids-oekaki';
const DB_VERSION = 1;
const STORE_NAME = 'drawing-sessions';
const CURRENT_KEY = 'current';
const SCHEMA_VERSION = 1;

export type StoredDrawingSession = {
  schemaVersion: number;
  savedAt: string;
  history: DrawingHistory;
};

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('保存場所を開けませんでした'));
  });
}

export async function saveDrawingSession(history: DrawingHistory): Promise<StoredDrawingSession> {
  const db = await openDb();
  const session: StoredDrawingSession = {
    schemaVersion: SCHEMA_VERSION,
    savedAt: new Date().toISOString(),
    history,
  };

  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, 'readwrite');
      transaction.objectStore(STORE_NAME).put(session, CURRENT_KEY);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error ?? new Error('作品を保存できませんでした'));
      transaction.onabort = () => reject(transaction.error ?? new Error('作品を保存できませんでした'));
    });
    return session;
  } finally {
    db.close();
  }
}

export async function loadDrawingSession(): Promise<StoredDrawingSession | null> {
  const db = await openDb();
  try {
    const value = await new Promise<StoredDrawingSession | undefined>((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, 'readonly');
      const request = transaction.objectStore(STORE_NAME).get(CURRENT_KEY);
      request.onsuccess = () => resolve(request.result as StoredDrawingSession | undefined);
      request.onerror = () => reject(request.error ?? new Error('保存した作品を読めませんでした'));
    });
    if (!value) return null;
    if (value.schemaVersion !== SCHEMA_VERSION) {
      throw new Error('この保存データは新しい形式です。アプリを更新してから開いてください。');
    }
    if (!value.history?.present || !Array.isArray(value.history.past) || !Array.isArray(value.history.future)) {
      throw new Error('保存データを安全に読み込めませんでした。');
    }
    return value;
  } finally {
    db.close();
  }
}
