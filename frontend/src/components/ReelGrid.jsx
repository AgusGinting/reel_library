// Snippet dari server menandai kata yang cocok dengan [[ ... ]].
function Highlight({ text }) {
  return text.split(/(\[\[.*?\]\])/g).map((part, i) =>
    part.startsWith("[[") ? <mark key={i}>{part.slice(2, -2)}</mark> : part,
  );
}

function ReelCard({ reel, onOpen }) {
  return (
    <button className="card" onClick={() => onOpen(reel.shortcode)}>
      <div className="thumb">
        {reel.thumb ? <img src={reel.thumb} alt="" loading="lazy" /> : <div className="thumb-empty" />}
        <span className="badge kind">{reel.kind === "carousel" ? "Slide" : "Video"}</span>
        {reel.is_learning === false && <span className="badge muted">Bukan materi</span>}
      </div>
      <div className="card-body">
        <h3 className="card-title">{reel.title}</h3>
        {reel.snippet && (
          <p className="card-snippet">
            <Highlight text={reel.snippet} />
          </p>
        )}
        <div className="card-meta">
          {reel.category && <span className="tag">{reel.category}</span>}
          <span className="author">{reel.author}</span>
        </div>
      </div>
    </button>
  );
}

export default function ReelGrid({ reels, loading, query, onOpen }) {
  if (loading && reels.length === 0) return <p className="notice">Memuat…</p>;
  if (!reels.length) {
    return (
      <p className="notice">
        {query ? `Tidak ada hasil untuk “${query}”.` : "Belum ada item di filter ini."}
      </p>
    );
  }
  return (
    <>
      <p className="result-count">{reels.length} item</p>
      <div className={`grid ${loading ? "dim" : ""}`}>
        {reels.map((r) => (
          <ReelCard key={r.shortcode} reel={r} onOpen={onOpen} />
        ))}
      </div>
    </>
  );
}
