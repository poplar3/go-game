// Хранение настроек (localStorage) и больших данных (IndexedDB) внутри приложения.
const DB = "gotrainer", OS = "kv";

function openDb() {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(OS);
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

export const store = {
  get(key, def = null) {
    try { const v = localStorage.getItem("gt/" + key); return v === null ? def : JSON.parse(v); } catch { return def; }
  },
  set(key, value) {
    try { localStorage.setItem("gt/" + key, JSON.stringify(value)); } catch { /* нет места */ }
  },
  async getBig(key) {
    if (typeof indexedDB === "undefined") return null;
    const db = await openDb();
    return new Promise((resolve) => {
      const r = db.transaction(OS).objectStore(OS).get(key);
      r.onsuccess = () => resolve(r.result ?? null);
      r.onerror = () => resolve(null);
    });
  },
  async setBig(key, value) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(OS, "readwrite");
      if (value === null) tx.objectStore(OS).delete(key); else tx.objectStore(OS).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  },
};
