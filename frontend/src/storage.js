import { useEffect, useState } from "react";

// Menyimpan keadaan tampilan agar halaman tidak "ter-reset" saat tab dibuka ulang
// (Chrome membekukan/membuang tab latar belakang saat RAM menipis, lalu memuat ulang).
//   session: per tab (filter, panel terbuka, scroll, draf) — hilang saat tab ditutup.
//   local  : permanen di browser ini (pilihan model, lebar chat, pekerjaan tambah link).
// Semua akses dibungkus try/catch: storage bisa penuh atau diblokir.

function store(kind) {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function loadJSON(key, fallback, kind = "session") {
  try {
    const raw = store(kind)?.getItem(key);
    return raw == null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function saveJSON(key, value, kind = "session") {
  try {
    if (value === undefined || value === null) store(kind)?.removeItem(key);
    else store(kind)?.setItem(key, JSON.stringify(value));
  } catch {
    // storage penuh/diblokir: abaikan, aplikasi tetap jalan tanpa cache
  }
}

/** useState yang nilainya disimpan & dipulihkan dari storage. */
export function usePersistentState(key, initial, kind = "session") {
  const [value, setValue] = useState(() => loadJSON(key, initial, kind));
  useEffect(() => saveJSON(key, value, kind), [key, value, kind]);
  return [value, setValue];
}
