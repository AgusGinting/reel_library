import { useCallback, useEffect, useState } from "react";
import { getJSON } from "./api";
import AddDialog from "./components/AddDialog";
import Toolbar from "./components/Toolbar";
import ReelGrid from "./components/ReelGrid";
import ReelDetail from "./components/ReelDetail";
import ChatPanel from "./components/ChatPanel";
import ErrorBoundary from "./components/ErrorBoundary";

const CHAT_MIN = 320;
const CHAT_DEFAULT = 440;
const GALLERY_MIN = 360; // sisakan ruang untuk galeri

function loadChatWidth() {
  try {
    return Number(localStorage.getItem("chatWidth")) || CHAT_DEFAULT;
  } catch {
    return CHAT_DEFAULT;
  }
}

export default function App() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [learning, setLearning] = useState(null); // "1" | "0" | "all"
  const [reels, setReels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatWidth, setChatWidth] = useState(loadChatWidth);
  const [addOpen, setAddOpen] = useState(false);
  const [addJob, setAddJob] = useState(null); // pekerjaan "tambah link" terakhir
  const [reloadKey, setReloadKey] = useState(0);

  // Setelah link baru selesai diproses: muat ulang status (kategori) & galeri.
  const onAddFinished = useCallback(() => {
    getJSON("/api/status").then(setStatus).catch(() => {});
    setReloadKey((k) => k + 1);
  }, []);

  // Pantau progres "tambah link" sampai selesai, meski dialognya ditutup.
  const addJobId = addJob && !addJob.done ? addJob.id : null;
  useEffect(() => {
    if (!addJobId) return;
    const timer = setInterval(() => {
      getJSON(`/api/jobs/${addJobId}`)
        .then((next) => {
          setAddJob(next);
          if (next.done) onAddFinished();
        })
        .catch(() => {}); // server sibuk / restart: coba lagi di putaran berikutnya
    }, 2000);
    return () => clearInterval(timer);
  }, [addJobId, onAddFinished]);

  const resizeChat = (width) =>
    setChatWidth(Math.round(Math.max(CHAT_MIN, Math.min(width, window.innerWidth - GALLERY_MIN))));

  useEffect(() => {
    try {
      localStorage.setItem("chatWidth", String(chatWidth));
    } catch {
      // penyimpanan browser tidak tersedia; lebar tetap berlaku selama halaman terbuka
    }
  }, [chatWidth]);

  useEffect(() => {
    getJSON("/api/status")
      .then((s) => {
        setStatus(s);
        // Filter "materi belajar" baru berarti setelah summarize.py dijalankan.
        setLearning(s.by_status.processed ? "1" : "all");
      })
      .catch(() => setError("Server tidak bisa dihubungi. Jalankan: python library.py"));
  }, []);

  useEffect(() => {
    if (learning === null) return;
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ learning });
      if (query.trim()) params.set("q", query.trim());
      if (category) params.set("category", category);
      setLoading(true);
      getJSON(`/api/reels?${params}`, { signal: ctrl.signal })
        .then((data) => {
          setReels(data);
          setLoading(false);
        })
        .catch((e) => {
          if (e.name !== "AbortError") {
            setError("Gagal memuat daftar reel.");
            setLoading(false);
          }
        });
    }, query ? 250 : 0); // jeda kecil saat mengetik
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [query, category, learning, reloadKey]);

  return (
    <div className={`app ${chatOpen ? "with-chat" : ""}`} style={{ "--chat-width": `${chatWidth}px` }}>
      <div className="main">
        <Toolbar
          status={status}
          query={query}
          onQuery={setQuery}
          category={category}
          onCategory={setCategory}
          learning={learning}
          onLearning={setLearning}
          chatOpen={chatOpen}
          onToggleChat={() => setChatOpen((v) => !v)}
          onAdd={() => setAddOpen(true)}
          adding={addJob !== null && !addJob.done}
        />
        {error ? (
          <p className="notice error">{error}</p>
        ) : (
          <ReelGrid reels={reels} loading={loading} query={query} onOpen={setSelected} />
        )}
      </div>

      {chatOpen && (
        <ErrorBoundary onClose={() => setChatOpen(false)}>
          <ChatPanel
            width={chatWidth}
            onResize={resizeChat}
            onResetWidth={() => setChatWidth(CHAT_DEFAULT)}
            aiReady={status?.ai_ready}
            onClose={() => setChatOpen(false)}
            onOpenReel={setSelected}
          />
        </ErrorBoundary>
      )}

      {addOpen && (
        <ErrorBoundary onClose={() => setAddOpen(false)}>
          <AddDialog
            job={addJob}
            onJob={setAddJob}
            onClose={() => setAddOpen(false)}
            onOpenReel={(sc) => {
              setAddOpen(false);
              setSelected(sc);
            }}
            aiReady={status?.ai_ready}
          />
        </ErrorBoundary>
      )}

      {selected && (
        <ErrorBoundary key={selected} onClose={() => setSelected(null)}>
          <ReelDetail shortcode={selected} onClose={() => setSelected(null)} />
        </ErrorBoundary>
      )}
    </div>
  );
}
