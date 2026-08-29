import type { ToolSettings } from '../domain/drawing';
import type { DrawingHistory } from '../state/useDrawingDocument';

const DB_NAME = 'kids-oekaki';
const DB_VERSION = 1;
const STORE_NAME = 'drawing-sessions';
const LEGACY_CURRENT_KEY = 'current';
const DRAFT_PREFIX = 'draft:';
const SCHEMA_VERSION = 2;

export type StoredDrawingSession = {
  schemaVersion: number;
  id: string;
  name: string;
  savedAt: string;
  history: DrawingHistory;
  settings?: ToolSettings;
};

type LegacyStoredDrawingSession = {
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

function validateHistory(history: DrawingHistory | undefined) {
  if (!history?.present || !Array.isArray(history.past) || !Array.isArray(history.future)) {
    throw new Error('保存データを安全に読み込めませんでした。');
  }
}

function defaultName(history: DrawingHistory, savedAt: string) {
  const template = history.present.template === '4koma' ? '4コマ' : history.present.template === 'diary' ? 'えにっき' : 'まっしろ';
  const date = new Date(savedAt);
  const stamp = Number.isNaN(date.getTime())
    ? ''
    : ` ${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  return `${template}${stamp}`;
}

async function readValue<T>(db: IDBDatabase, key: IDBValidKey): Promise<T | undefined> {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, 'readonly');
    const request = transaction.objectStore(STORE_NAME).get(key);
    request.onsuccess = () => resolve(request.result as T | undefined);
    request.onerror = () => reject(request.error ?? new Error('保存した作品を読めませんでした'));
  });
}

async function putValue(db: IDBDatabase, key: IDBValidKey, value: unknown): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, 'readwrite');
    transaction.objectStore(STORE_NAME).put(value, key);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error('作品を保存できませんでした'));
    transaction.onabort = () => reject(transaction.error ?? new Error('作品を保存できませんでした'));
  });
}

async function deleteValue(db: IDBDatabase, key: IDBValidKey): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, 'readwrite');
    transaction.objectStore(STORE_NAME).delete(key);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error('作品を削除できませんでした'));
    transaction.onabort = () => reject(transaction.error ?? new Error('作品を削除できませんでした'));
  });
}

async function migrateLegacyCurrent(db: IDBDatabase): Promise<StoredDrawingSession | null> {
  const legacy = await readValue<LegacyStoredDrawingSession>(db, LEGACY_CURRENT_KEY);
  if (!legacy) return null;
  validateHistory(legacy.history);
  const id = crypto.randomUUID();
  const savedAt = legacy.savedAt || new Date().toISOString();
  const migrated: StoredDrawingSession = {
    schemaVersion: SCHEMA_VERSION,
    id,
    name: defaultName(legacy.history, savedAt),
    savedAt,
    history: legacy.history,
  };
  await putValue(db, `${DRAFT_PREFIX}${id}`, migrated);
  await deleteValue(db, LEGACY_CURRENT_KEY);
  return migrated;
}

export async function saveDrawingSession(
  id: string,
  history: DrawingHistory,
  settings: ToolSettings,
  name?: string,
): Promise<StoredDrawingSession> {
  const db = await openDb();
  const savedAt = new Date().toISOString();
  try {
    const existing = await readValue<StoredDrawingSession>(db, `${DRAFT_PREFIX}${id}`);
    const session: StoredDrawingSession = {
      schemaVersion: SCHEMA_VERSION,
      id,
      name: name ?? existing?.name ?? defaultName(history, savedAt),
      savedAt,
      history,
      settings,
    };
    await putValue(db, `${DRAFT_PREFIX}${id}`, session);
    return session;
  } finally {
    db.close();
  }
}

export async function listDrawingSessions(): Promise<StoredDrawingSession[]> {
  const db = await openDb();
  try {
    await migrateLegacyCurrent(db);
    const entries = await new Promise<Array<{ key: IDBValidKey; value: StoredDrawingSession }>>((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, 'readonly');
      const store = transaction.objectStore(STORE_NAME);
      const keysRequest = store.getAllKeys();
      const valuesRequest = store.getAll();
      transaction.oncomplete = () => {
        const keys = keysRequest.result;
        const values = valuesRequest.result as StoredDrawingSession[];
        resolve(keys.map((key, index) => ({ key, value: values[index] })));
      };
      transaction.onerror = () => reject(transaction.error ?? new Error('保存した作品を読めませんでした'));
    });

    return entries
      .filter(({ key }) => typeof key === 'string' && key.startsWith(DRAFT_PREFIX))
      .map(({ value }) => {
        validateHistory(value.history);
        if (value.schemaVersion !== SCHEMA_VERSION) {
          throw new Error('この保存データは新しい形式です。アプリを更新してから開いてください。');
        }
        return value;
      })
      .sort((a, b) => b.savedAt.localeCompare(a.savedAt));
  } finally {
    db.close();
  }
}

export async function loadDrawingSession(id: string): Promise<StoredDrawingSession | null> {
  const db = await openDb();
  try {
    const value = await readValue<StoredDrawingSession>(db, `${DRAFT_PREFIX}${id}`);
    if (!value) return null;
    if (value.schemaVersion !== SCHEMA_VERSION) {
      throw new Error('この保存データは新しい形式です。アプリを更新してから開いてください。');
    }
    validateHistory(value.history);
    return value;
  } finally {
    db.close();
  }
}

export async function deleteDrawingSession(id: string): Promise<void> {
  const db = await openDb();
  try {
    await deleteValue(db, `${DRAFT_PREFIX}${id}`);
  } finally {
    db.close();
  }
}
