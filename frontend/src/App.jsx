import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { getJSON } from "./api";
import { loadJSON, saveJSON, usePersistentState } from "./storage";
import AddDialog from "./components/AddDialog";
import Toolbar from "./components/Toolbar";
import ReelGrid from "./components/ReelGrid";
import ReelDetail from "./components/ReelDetail";
import ChatPanel from "./components/ChatPanel";
import ErrorBoundary from "./components/ErrorBoundary";

const CHAT_MIN = 320;
const CHAT_DEFAULT = 440;
const GALLERY_MIN = 360; // sisakan ruang untuk galeri
const MAX_JOBS = 10;     // pekerjaan "tambah link" yang diingat

export default function App() {
  // Keadaan tampilan disimpan per tab, jadi tidak hilang saat tab dibuka ulang.
  const [query, setQuery] = usePersistentState("ui:query", "");
  const [category, setCategory] = usePersistentState("ui:category", "");
  const [learning, setLearning] = usePersistentState("ui:learning", null); // "1" | "0" | "all"
  const [selected, setSelected] = usePersistentState("ui:selected", null);
  const [chatOpen, setChatOpen] = usePersistentState("ui:chatOpen", false);
  const [addOpen, setAddOpen] = usePersistentState("ui:addOpen", false);
  const [chatWidth, setChatWidth] = usePersistentState("chatWidth", CHAT_DEFAULT, "local");
  const [jobIds, setJobIds] = usePersistentState("addJobs", [], "local");

  const [status, setStatus] = useState(() => loadJSON("cache:status", null));
  const [error, setError] = useState(null);
  const [reels, setReels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [jobs, setJobs] = useState([]); // pekerjaan "tambah link" (terbaru dulu)
  const [reloadKey, setReloadKey] = useState(0);

  const resizeChat = (width) =>
    setChatWidth(Math.round(Math.max(CHAT_MIN, Math.min(width, window.innerWidth - GALLERY_MIN))));

  const loadStatus = useCallback(
    () =>
      getJSON("/api/status").then((s) => {
        setStatus(s);
        saveJSON("cache:status", s);
        return s;
      }),
    [],
  );

  useEffect(() => {
    loadStatus()
      .then((s) => {
        // Filter "materi belajar" baru berarti setelah summarize.py dijalankan.
        setLearning((current) => current ?? (s.by_status.processed ? "1" : "all"));
      })
      .catch(() => setError("Server tidak bisa dihubungi. Jalankan: python library.py"));
  }, [loadStatus, setLearning]);

  // Daftar reel: tampilkan cache lebih dulu, lalu perbarui dari server di belakang.
  useEffect(() => {
    if (learning === null) return;
    const params = new URLSearchParams({ learning });
    if (query.trim()) params.set("q", query.trim());
    if (category) params.set("category", category);
    const cacheKey = `cache:reels:${params}`;
    const cached = loadJSON(cacheKey, null);
    if (cached) {
      setReels(cached);
      setLoading(false);
    }

    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      if (!cached) setLoading(true);
      getJSON(`/api/reels?${params}`, { signal: ctrl.signal })
        .then((data) => {
          setReels(data);
          setLoading(false);
          setError(null);
          saveJSON(cacheKey, data);
        })
        .catch((e) => {
          if (e.name !== "AbortError" && !cached) {
            setError("Gagal memuat daftar reel.");
            setLoading(false);
          }
        });
    }, query && !cached ? 250 : 0); // jeda kecil saat mengetik
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [query, category, learning, reloadKey]);

  // Pulihkan posisi scroll galeri sekali, setelah daftar reel pertama kali tampil.
  const scrollRestored = useRef(false);
  useLayoutEffect(() => {
    if (scrollRestored.current || !reels.length) return;
    scrollRestored.current = true;
    const y = loadJSON("ui:scrollY", 0);
    if (y) window.scrollTo(0, y);
  }, [reels]);
  useEffect(() => {
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => saveJSON("ui:scrollY", Math.round(window.scrollY)));
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // --- pekerjaan "tambah link" -------------------------------------------
  const onAddFinished = useCallback(() => {
    loadStatus().catch(() => {});
    setReloadKey((k) => k + 1);
  }, [loadStatus]);

  const addJob = useCallback(
    (job) => {
      setJobs((list) => [job, ...list.filter((j) => j.id !== job.id)].slice(0, MAX_JOBS));
      setJobIds((ids) => [job.id, ...ids.filter((id) => id !== job.id)].slice(0, MAX_JOBS));
    },
    [setJobIds],
  );

  // Muat ulang pekerjaan yang diingat (job di server hilang bila server di-restart).
  useEffect(() => {
    Promise.all(jobIds.map((id) => getJSON(`/api/jobs/${id}`).catch(() => null))).then((list) => {
      const alive = list.filter(Boolean);
      setJobs(alive);
      setJobIds(alive.map((j) => j.id));
    });
    // hanya sekali saat halaman dibuka
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pantau pekerjaan yang belum selesai, meski dialognya ditutup.
  const runningIds = jobs.filter((j) => !j.done).map((j) => j.id).join(",");
  useEffect(() => {
    if (!runningIds) return;
    const timer = setInterval(() => {
      runningIds.split(",").forEach((id) =>
        getJSON(`/api/jobs/${id}`)
          .then((next) => {
            setJobs((list) => list.map((j) => (j.id === id ? next : j)));
            if (next.done) onAddFinished();
          })
          .catch(() => {}), // server sibuk / restart: coba lagi di putaran berikutnya
      );
    }, 2000);
    return () => clearInterval(timer);
  }, [runningIds, onAddFinished]);

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
          adding={Boolean(runningIds)}
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
            jobs={jobs}
            onJob={addJob}
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
