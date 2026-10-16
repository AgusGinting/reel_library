import { useEffect, useState } from "react";
import { postJSON } from "../api";

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

// Progres pekerjaan dipantau oleh App (tetap jalan walau dialog ditutup).
export default function AddDialog({ job, onJob, onClose, onOpenReel, aiReady }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);

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

  const running = job && !job.done;

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
            disabled={running}
          />
          {error && <p className="notice error">{error}</p>}
          <div className="add-actions">
            {running && <span className="hint">Memproses… (bisa beberapa menit per video)</span>}
            <button className="btn primary" disabled={!text.trim() || sending || running}>
              {sending ? "Mengirim…" : "Tambahkan"}
            </button>
          </div>
        </form>

        {job && (
          <ul className="job-list">
            {job.items.map((it) => (
              <li key={it.input} className={`job-item stage-${it.stage}`}>
                <span className="job-stage">
                  {!FINAL.has(it.stage) && <span className="spinner" aria-hidden />}
                  {STAGES[it.stage] ?? it.stage}
                </span>
                <span className="job-text">
                  <span className="job-title">{it.title || it.input}</span>
                  {it.message && <span className="job-msg">{it.message}</span>}
                </span>
                {it.shortcode && ["done", "exists", "partial"].includes(it.stage) && (
                  <button className="btn" onClick={() => onOpenReel(it.shortcode)}>Lihat</button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
