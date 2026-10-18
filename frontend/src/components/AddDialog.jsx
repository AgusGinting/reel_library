import { useCallback, useEffect, useMemo, useState } from "react";
import { getJSON, postJSON } from "../api";
import { usePersistentState } from "../storage";

const STAGES = {
  queued: "Antre",
  resolve: "Memeriksa link",
  download: "Mengunduh",
  transcribe: "Transkrip suara",
  ocr: "Membaca teks layar",
  summarize: "Meringkas",
  done: "Selesai",
  exists: "Sudah ada",
  partial: "Sebagian",
  error: "Gagal",
};
const FINAL = new Set(["done", "exists", "partial", "error"]);
const RETRYABLE = new Set(["error", "partial"]);

function RetryButton({ onClick, busy, label = "Coba lagi" }) {
  return (
    <button className="btn retry-btn" onClick={onClick} disabled={busy} title={label} aria-label={label}>
      <span className={`retry-icon ${busy ? "spinning" : ""}`} aria-hidden>↻</span>
      <span className="retry-label">{label}</span>
    </button>
  );
}

// Progres pekerjaan dipantau oleh App (tetap jalan walau dialog ditutup).
export default function AddDialog({ jobs, onJob, onClose, onOpenReel, aiReady }) {
  const [text, setText] = usePersistentState("ui:addDraft", ""); // draf link tidak hilang
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState([]);   // item belum selesai di database
  const [retrying, setRetrying] = useState({}); // key -> true selama permintaan dikirim
  const [instagram, setInstagram] = useState(null);

  const running = jobs.some((j) => !j.done);

  const refreshPending = useCallback(() => {
    getJSON("/api/pending").then(setPending).catch(() => {});
    getJSON("/api/instagram").then(setInstagram).catch(() => {});
  }, []);
  // Muat ulang daftar "belum selesai" saat dialog dibuka & tiap pekerjaan selesai.
  const doneCount = jobs.filter((j) => j.done).length;
  useEffect(refreshPending, [refreshPending, doneCount]);

  // Selama jendela login Instagram terbuka, pantau sampai login selesai.
  useEffect(() => {
    if (!instagram?.login_running) return;
    const timer = setInterval(() => getJSON("/api/instagram").then(setInstagram).catch(() => {}), 2000);
    return () => clearInterval(timer);
  }, [instagram?.login_running]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(e) {
    e.preventDefault();
    setSending(true);
    setError(null);
    try {
      onJob(await postJSON("/api/add", { text }));
      setText("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  // Ulangi item: yang sudah dikenal di database lewat /api/retry; link yang bahkan
  // gagal dikenali (tanpa shortcode) dikirim ulang sebagai link baru.
  async function retry(key, { shortcodes, input }) {
    setRetrying((r) => ({ ...r, [key]: true }));
    setError(null);
    try {
      onJob(shortcodes?.length
        ? await postJSON("/api/retry", { shortcodes })
        : await postJSON("/api/add", { text: input }));
      refreshPending();
    } catch (err) {
      setError(err.message);
    } finally {
      setRetrying((r) => ({ ...r, [key]: false }));
    }
  }

  async function loginInstagram() {
    try {
      setInstagram(await postJSON("/api/instagram/login", {}));
    } catch (err) {
      setError(err.message);
    }
  }

  // Gabungkan item semua pekerjaan (terbaru dulu); satu link hanya tampil sekali.
  const items = useMemo(() => {
    const seen = new Set();
    const list = [];
    for (const job of jobs) {
      for (const it of job.items) {
        const key = it.shortcode || it.input;
        if (!seen.has(key)) {
          seen.add(key);
          list.push({ ...it, key });
        }
      }
    }
    return list;
  }, [jobs]);
  const shown = new Set(items.map((it) => it.key));
  const leftovers = pending.filter((p) => !shown.has(p.shortcode) && !p.running);
  const failed = [...items.filter((it) => RETRYABLE.has(it.stage) && it.shortcode), ...leftovers];
  // Postingan publik bisa diunduh tanpa login; tawarkan login hanya bila ada item
  // yang benar-benar gagal karena butuh login (privat/dibatasi).
  const needsLogin =
    instagram && !instagram.logged_in &&
    items.some((it) => it.stage === "error" && /Login Instagram/.test(it.message || ""));

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal add-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Tutup">×</button>
        <h2>Tambah materi</h2>
        <p className="hint">
          Tempel satu atau beberapa link (satu per baris): reel/postingan Instagram, YouTube, TikTok,
          dan situs video lain yang didukung. Link akan diunduh, ditranskrip, dibaca teks layarnya,
          lalu diringkas AI. Kamu boleh menutup jendela ini; prosesnya tetap berjalan.
        </p>
        {!aiReady && (
          <p className="notice error">
            API key Claude belum diatur, jadi item hanya akan diunduh &amp; ditranskrip (tanpa ringkasan).
          </p>
        )}

        <form onSubmit={submit}>
          <textarea
            className="add-input"
            rows={4}
            placeholder={"https://www.instagram.com/reel/...\nhttps://youtu.be/..."}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {error && <p className="notice error">{error}</p>}
          <div className="add-actions">
            {running && <span className="hint">Memproses… (bisa beberapa menit per video)</span>}
            <button className="btn primary" disabled={!text.trim() || sending}>
              {sending ? "Mengirim…" : "Tambahkan"}
            </button>
          </div>
        </form>

        {needsLogin && (
          <div className="login-box">
            <p>
              <strong>Butuh login Instagram.</strong> Postingan yang gagal bersifat privat/dibatasi, jadi hanya bisa
              diunduh dengan akunmu. Jendela login akan terbuka di komputer ini; setelah login, jendelanya
              tertutup sendiri.
            </p>
            {instagram.login_running ? (
              <span className="hint"><span className="spinner" aria-hidden /> Menunggu kamu login di jendela browser…</span>
            ) : (
              <button className="btn primary" onClick={loginInstagram}>Login Instagram</button>
            )}
          </div>
        )}
        {instagram?.logged_in && failed.some((f) => (f.url || "").includes("instagram.com")) && (
          <p className="hint ok">✓ Sudah login Instagram — silakan coba lagi item yang gagal.</p>
        )}

        {failed.length > 1 && (
          <div className="add-actions">
            <RetryButton
              label={`Coba lagi semua (${failed.length})`}
              busy={retrying.all}
              onClick={() => retry("all", { shortcodes: failed.map((f) => f.shortcode) })}
            />
          </div>
        )}

        {items.length > 0 && (
          <ul className="job-list">
            {items.map((it) => (
              <li key={it.key} className={`job-item stage-${it.stage}`}>
                <span className="job-stage">
                  {!FINAL.has(it.stage) && <span className="spinner" aria-hidden />}
                  {STAGES[it.stage] ?? it.stage}
                </span>
                <span className="job-text">
                  <span className="job-title">{it.title || it.input}</span>
                  {it.message && <span className="job-msg">{it.message}</span>}
                </span>
                {RETRYABLE.has(it.stage) && (
                  <RetryButton
                    busy={retrying[it.key]}
                    onClick={() => retry(it.key, { shortcodes: it.shortcode ? [it.shortcode] : [], input: it.input })}
                  />
                )}
                {it.shortcode && ["done", "exists", "partial"].includes(it.stage) && (
                  <button className="btn" onClick={() => onOpenReel(it.shortcode)}>Lihat</button>
                )}
              </li>
            ))}
          </ul>
        )}

        {leftovers.length > 0 && (
          <>
            <h3 className="add-subtitle">Belum selesai dari sebelumnya ({leftovers.length})</h3>
            <ul className="job-list">
              {leftovers.map((p) => (
                <li key={p.shortcode} className="job-item stage-error">
                  <span className="job-stage">Tertunda</span>
                  <span className="job-text">
                    <span className="job-title">{p.title}</span>
                    <span className="job-msg">Berhenti di tahap '{p.status}'</span>
                  </span>
                  <RetryButton busy={retrying[p.shortcode]}
                    onClick={() => retry(p.shortcode, { shortcodes: [p.shortcode] })} />
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
