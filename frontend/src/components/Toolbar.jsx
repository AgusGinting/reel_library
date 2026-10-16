const LEARNING_OPTIONS = [
  { value: "1", label: "Materi belajar" },
  { value: "all", label: "Semua" },
  { value: "0", label: "Lainnya" },
];

export default function Toolbar({
  status, query, onQuery, category, onCategory, learning, onLearning,
  chatOpen, onToggleChat, onAdd, adding,
}) {
  const processed = status?.by_status?.processed ?? 0;
  const categories = status?.categories ?? [];

  return (
    <header className="toolbar">
      <div className="toolbar-row">
        <h1 className="brand">
          Perpustakaan Reel
          {status && <span className="brand-count">{status.total} item</span>}
        </h1>
        <input
          className="search"
          type="search"
          placeholder="Cari di caption, transkrip, teks layar, ringkasan…"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
        />
        <button className="btn" onClick={onAdd} title="Tambah materi dari link">
          {adding && <span className="spinner" aria-hidden />}+ Tambah
        </button>
        <button className={`btn primary ${chatOpen ? "active" : ""}`} onClick={onToggleChat}>
          Tanya AI
        </button>
      </div>

      <div className="toolbar-row filters">
        <div className="segmented" title={processed ? "" : "Jalankan summarize.py dulu"}>
          {LEARNING_OPTIONS.map((o) => (
            <button
              key={o.value}
              className={learning === o.value ? "on" : ""}
              disabled={!processed && o.value !== "all"}
              onClick={() => onLearning(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>

        {categories.length > 0 ? (
          <div className="chips">
            <button className={`chip ${category === "" ? "on" : ""}`} onClick={() => onCategory("")}>
              Semua kategori
            </button>
            {categories.map((c) => (
              <button
                key={c.name}
                className={`chip ${category === c.name ? "on" : ""}`}
                onClick={() => onCategory(category === c.name ? "" : c.name)}
              >
                {c.name} <span className="chip-count">{c.count}</span>
              </button>
            ))}
          </div>
        ) : (
          status && (
            <span className="hint">
              Kategori &amp; judul muncul setelah menjalankan <code>python summarize.py</code>
            </span>
          )
        )}
      </div>
    </header>
  );
}
