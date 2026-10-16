import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { streamChat } from "../api";

const SUGGESTIONS = [
  "Rangkum semua tips riset dan skripsi yang pernah dikirim ke DM",
  "Aku mau belajar machine learning dari nol, reel mana yang harus kutonton dulu?",
  "Tool AI apa saja yang pernah direkomendasikan, dan untuk apa?",
];

// AI merujuk item dengan id pendek [R12]; ubah jadi tautan berlabel judul singkat.
const CITE_RE = /\[(R\d+)\](?!\()/g;
const shortTitle = (t) => (t.length > 30 ? `${t.slice(0, 30)}…` : t).replace(/[[\]]/g, "");
const linkCitations = (text, refs) =>
  text.replace(CITE_RE, (match, ref) =>
    refs?.[ref] ? `[${shortTitle(refs[ref].title)}](#reel-${refs[ref].shortcode})` : match,
  );

function Answer({ msg, refs, onOpenReel }) {
  const components = {
    a: ({ href, children }) =>
      href?.startsWith("#reel-") ? (
        <button className="cite" onClick={() => onOpenReel(href.slice(6))}>{children}</button>
      ) : (
        <a href={href} target="_blank" rel="noreferrer">{children}</a>
      ),
  };
  return (
    <div className="msg assistant">
      {msg.text ? (
        <Markdown components={components}>{linkCitations(msg.text, refs)}</Markdown>
      ) : (
        !msg.error && <span className="typing">Membaca perpustakaan…</span>
      )}
      {msg.error && <p className="notice error">{msg.error}</p>}
      {msg.sources?.length > 0 && (
        <div className="sources">
          <strong>Sumber</strong>
          {msg.sources.map((s) => (
            <button key={s.shortcode} className="source" onClick={() => onOpenReel(s.shortcode)}>
              {s.title}
            </button>
          ))}
        </div>
      )}
      {msg.usage && (
        <div className="usage">
          token: {msg.usage.input.toLocaleString()} input
          {msg.usage.cache_write > 0 && <> · {msg.usage.cache_write.toLocaleString()} ditulis ke cache</>}
          {msg.usage.cache_read > 0 && <> · {msg.usage.cache_read.toLocaleString()} dibaca dari cache</>}
          {" · "}{msg.usage.output.toLocaleString()} output
        </div>
      )}
    </div>
  );
}

// Pegangan di tepi kiri panel: seret untuk mengubah lebar, panah kiri/kanan
// untuk keyboard, klik ganda untuk kembali ke lebar awal.
function Resizer({ width, onResize, onReset }) {
  function onPointerDown(e) {
    e.preventDefault();
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    document.body.classList.add("resizing");
    const move = (ev) => onResize(window.innerWidth - ev.clientX);
    const stop = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
      document.body.classList.remove("resizing");
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  }

  return (
    <div
      className="chat-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="Ubah lebar panel chat"
      aria-valuenow={width}
      tabIndex={0}
      title="Seret untuk mengubah lebar · klik ganda untuk lebar awal"
      onPointerDown={onPointerDown}
      onDoubleClick={onReset}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") onResize(width + 24);
        else if (e.key === "ArrowRight") onResize(width - 24);
      }}
    />
  );
}

export default function ChatPanel({ width, onResize, onResetWidth, aiReady, onClose, onOpenReel }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const conversationId = useRef(null);
  const [refs, setRefs] = useState(null);
  const abortRef = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    // Jangan di-return: di Chromium baru scrollIntoView() mengembalikan Promise,
    // dan React akan mencoba memanggilnya sebagai fungsi cleanup -> halaman crash.
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);
  useEffect(() => () => abortRef.current?.abort(), []);

  // Perbarui pesan AI terakhir (yang sedang dialirkan).
  const patchLast = (fn) =>
    setMessages((prev) => [...prev.slice(0, -1), fn(prev[prev.length - 1])]);

  async function send(question) {
    question = question.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    setMessages((prev) => [...prev, { role: "user", text: question }, { role: "assistant", text: "" }]);
    abortRef.current = new AbortController();
    try {
      await streamChat({
        question,
        conversationId: conversationId.current,
        signal: abortRef.current.signal,
        onEvent: (event, data) => {
          if (event === "meta") {
            conversationId.current = data.conversation_id;
            setRefs(data.refs);
          }
          else if (event === "text") patchLast((m) => ({ ...m, text: m.text + data.text }));
          else if (event === "done") patchLast((m) => ({ ...m, sources: data.sources, usage: data.usage }));
          else if (event === "error") patchLast((m) => ({ ...m, error: data.message }));
        },
      });
    } catch (e) {
      if (e.name !== "AbortError") patchLast((m) => ({ ...m, error: e.message }));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    abortRef.current?.abort();
    conversationId.current = null;
    setRefs(null);
    setMessages([]);
    setBusy(false);
  }

  return (
    <aside className="chat">
      <Resizer width={width} onResize={onResize} onReset={onResetWidth} />
      <div className="chat-head">
        <h2>Tanya AI</h2>
        <button className="btn" onClick={reset} disabled={!messages.length}>Percakapan baru</button>
        <button className="close" onClick={onClose} aria-label="Tutup">×</button>
      </div>

      <div className="chat-body">
        {!aiReady && (
          <p className="notice error">
            API key Claude belum diatur. Isi <code>ANTHROPIC_API_KEY</code> di file <code>.env</code>, lalu
            jalankan ulang server.
          </p>
        )}
        {messages.length === 0 && aiReady && (
          <div className="suggestions">
            <p className="hint">Tanya apa saja tentang isi perpustakaanmu. Jawaban menyebut reel sumbernya.</p>
            {SUGGESTIONS.map((s) => (
              <button key={s} className="suggestion" onClick={() => send(s)}>{s}</button>
            ))}
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="msg user">{m.text}</div>
          ) : (
            <Answer key={i} msg={m} refs={refs} onOpenReel={onOpenReel} />
          ),
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <textarea
          rows={2}
          placeholder={aiReady ? "Tulis pertanyaan… (Enter kirim, Shift+Enter baris baru)" : "API key belum diatur"}
          value={input}
          disabled={!aiReady}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
        />
        <button className="btn primary" disabled={!aiReady || busy || !input.trim()}>
          {busy ? "…" : "Kirim"}
        </button>
      </form>
    </aside>
  );
}
