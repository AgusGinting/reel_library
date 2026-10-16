import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import { getJSON } from "../api";

function MediaViewer({ media, poster }) {
  const [index, setIndex] = useState(0);
  if (!media.length) return <div className="media-empty">Media tidak tersedia</div>;

  const item = media[index];
  const many = media.length > 1;
  return (
    <div className="media">
      {item.type === "video" ? (
        <video key={item.url} src={item.url} poster={index === 0 ? poster : undefined} controls playsInline />
      ) : (
        <img key={item.url} src={item.url} alt={`Slide ${index + 1}`} />
      )}
      {many && (
        <div className="media-nav">
          <button className="btn" disabled={index === 0} onClick={() => setIndex(index - 1)}>‹</button>
          <span>{index + 1} / {media.length}</span>
          <button className="btn" disabled={index === media.length - 1} onClick={() => setIndex(index + 1)}>›</button>
        </div>
      )}
    </div>
  );
}

const TEXT_TABS = [
  { key: "transcript", label: "Transkrip" },
  { key: "screen_text", label: "Teks layar" },
  { key: "caption", label: "Caption" },
];

export default function ReelDetail({ shortcode, onClose }) {
  const [reel, setReel] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState(null);

  useEffect(() => {
    setReel(null);
    setError(null);
    getJSON(`/api/reels/${shortcode}`)
      .then((r) => {
        setReel(r);
        setTab(TEXT_TABS.find((t) => r[t.key]?.trim())?.key ?? "caption");
      })
      .catch(() => setError("Gagal memuat detail."));
  }, [shortcode]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Tutup">×</button>
        {error && <p className="notice error">{error}</p>}
        {!reel && !error && <p className="notice">Memuat…</p>}
        {reel && (
          <div className="detail">
            <MediaViewer key={reel.shortcode} media={reel.media} poster={reel.thumb} />
            <div className="detail-info">
              <h2>{reel.title}</h2>
              <p className="detail-meta">
                {reel.author}
                {reel.posted_at && <> · {reel.posted_at}</>}
                {" · "}
                <a href={reel.url} target="_blank" rel="noreferrer">Buka di Instagram ↗</a>
              </p>

              <div className="tags">
                {reel.category && <span className="tag strong">{reel.category}</span>}
                {reel.is_learning === false && <span className="tag muted">Bukan materi belajar</span>}
                {reel.topics.map((t) => <span key={t} className="tag">#{t}</span>)}
              </div>

              {reel.summary ? (
                <div className="summary"><Markdown>{reel.summary}</Markdown></div>
              ) : (
                <p className="hint">Belum diringkas AI (jalankan <code>python summarize.py</code>).</p>
              )}

              <div className="tabs">
                {TEXT_TABS.map((t) => (
                  <button key={t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>
                    {t.label}
                  </button>
                ))}
              </div>
              <pre className="fulltext">{reel[tab]?.trim() || "(kosong)"}</pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
