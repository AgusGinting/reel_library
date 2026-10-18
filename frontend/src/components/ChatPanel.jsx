import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { getJSON, streamChat } from "../api";
import { usePersistentState } from "../storage";

const SUGGESTIONS = [
  "Rangkum semua tips riset dan skripsi yang pernah dikirim ke DM",
  "Aku mau belajar machine learning dari nol, reel mana yang harus kutonton dulu?",
  "Tool AI apa saja yang pernah direkomendasikan, dan untuk apa?",
];

// AI merujuk item dengan id pendek [R12]; ubah jadi nomor catatan kaki yang bisa diklik
// (judul tampil saat kursor diarahkan). Nomor mengikuti urutan kemunculan, sama dengan
// urutan daftar "Sumber" dari server. Model sering sudah menulis judulnya di kalimat,
// jadi label berupa judul akan tampil dua kali.
const CITE_RE = /\[(R\d+)\](?!\()/g;
const linkCitations = (text, refs) => {
  const order = {};
  return text.replace(CITE_RE, (match, ref) => {
    if (!refs?.[ref]) return match;
    order[ref] ??= Object.keys(order).length + 1;
    const title = refs[ref].title.replace(/["\\]/g, "");
    return `[${order[ref]}](#reel-${refs[ref].shortcode} "${title}")`;
  });
};

function Answer({ msg, refs, onOpenReel, labelOf }) {
  const components = {
    // Nomor ditampilkan lewat CSS (data-n) agar tidak ikut tersalin saat teks diblok untuk dibalas.
    a: ({ href, title, children }) =>
      href?.startsWith("#reel-") ? (
        <button className="cite" data-n={String(children)} title={title}
          aria-label={`Sumber ${children}: ${title}`} onClick={() => onOpenReel(href.slice(6))} />
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
          {msg.sources.map((s, i) => (
            <button key={s.shortcode} className="source" onClick={() => onOpenReel(s.shortcode)}>
              <span className="source-num">{i + 1}</span>
              {s.title}
            </button>
          ))}
        </div>
      )}
      {msg.usage && (
        <div className="usage">
          {msg.model && <><strong>{labelOf(msg.model)}</strong> · </>}
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

// --- Balas teks yang diblok ------------------------------------------------
// Kutipan dikirim (dan disimpan di riwayat) sebagai blockquote markdown di depan
// pertanyaan, sehingga Claude tahu bagian mana yang dimaksud.
const QUOTE_MAX = 1500;
const toQuoteBlock = (quote) =>
  quote.split("\n").filter((line) => line.trim()).map((line) => `> ${line}`).join("\n");

function splitQuote(text) {
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length && lines[i].startsWith(">")) i++;
  if (!i) return { quote: null, body: text };
  return {
    quote: lines.slice(0, i).map((line) => line.replace(/^> ?/, "")).join("\n"),
    body: lines.slice(i).join("\n").trim(),
  };
}

function UserMessage({ text }) {
  const { quote, body } = splitQuote(text);
  return (
    <div className="msg user">
      {quote && <div className="msg-quote">{quote}</div>}
      {body}
    </div>
  );
}

// Percakapan yang sedang dibuka & model pilihan diingat agar tetap sama setelah refresh.
const CHAT_KEY = "chatId";
const MODEL_KEY = "chatModel";
function loadPref(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function savePref(key, value) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // penyimpanan browser tidak tersedia; riwayat tetap ada di server
  }
}
const savedChatId = () => loadPref(CHAT_KEY);
const rememberChatId = (id) => savePref(CHAT_KEY, id);

// Pesan tersimpan + jawaban yang masih dibuat server (bila ada).
const withPending = (chat) =>
  chat.pending
    ? [...chat.messages, { role: "user", text: chat.pending.question },
      { role: "assistant", text: chat.pending.text, resuming: true }]
    : chat.messages;

const formatDate = (s) =>
  new Date(s.replace(" ", "T")).toLocaleString("id-ID", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });

function History({ activeId, onOpen, onBack }) {
  const [chats, setChats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getJSON("/api/chats").then(setChats).catch(() => setError("Gagal memuat riwayat."));
  }, []);

  async function remove(chat) {
    if (!window.confirm(`Hapus percakapan "${chat.title}"?`)) return;
    const res = await fetch(`/api/chats/${chat.id}`, { method: "DELETE" });
    if (res.ok || res.status === 404) {
      setChats((list) => list.filter((c) => c.id !== chat.id));
      if (chat.id === activeId) onOpen(null);
    }
  }

  return (
    <div className="history">
      <button className="btn" onClick={onBack}>‹ Kembali</button>
      {error && <p className="notice error">{error}</p>}
      {chats === null && !error && <p className="hint">Memuat…</p>}
      {chats?.length === 0 && <p className="hint">Belum ada percakapan tersimpan.</p>}
      <ul className="history-list">
        {chats?.map((c) => (
          <li key={c.id} className={c.id === activeId ? "active" : ""}>
            <button className="history-open" onClick={() => onOpen(c.id)}>
              <span className="history-title">{c.title}</span>
              <span className="history-meta">
                {formatDate(c.updated_at)} · {Math.ceil(c.messages / 2)} pertanyaan
              </span>
            </button>
            <button className="history-delete" onClick={() => remove(c)} aria-label="Hapus percakapan"
              title="Hapus percakapan">×</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ChatPanel({ width, onResize, onResetWidth, aiReady, onClose, onOpenReel }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = usePersistentState("ui:chatDraft", ""); // draf tidak hilang saat tab dibuka ulang
  const [busy, setBusy] = useState(false);
  const [view, setView] = usePersistentState("ui:chatView", "chat"); // chat | history
  const [resuming, setResuming] = useState(null); // id percakapan yang jawabannya masih dibuat server
  const [chatId, setChatId] = useState(null);
  const conversationId = useRef(null);
  const [refs, setRefs] = useState(null);
  const abortRef = useRef(null);
  const bottomRef = useRef(null);
  const chatRef = useRef(null);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);
  const [quote, setQuote] = usePersistentState("ui:chatQuote", null); // teks yang sedang dibalas
  const [selection, setSelection] = useState(null); // {text, top, left} tombol "Balas"
  const [models, setModels] = useState([]);         // dari /api/models
  const [modelId, setModelId] = useState(() => loadPref(MODEL_KEY));

  useEffect(() => {
    getJSON("/api/models")
      .then(({ models: list, default: fallback }) => {
        setModels(list);
        setModelId((current) => (list.some((m) => m.id === current) ? current : fallback));
      })
      .catch(() => {});
  }, []);

  const model = models.find((m) => m.id === modelId);
  // Siap bila model terpilih tersedia; sebelum daftar model termuat, pakai status Claude.
  const ready = model ? model.available : aiReady;
  const labelOf = (id) => models.find((m) => m.id === id)?.label ?? id;

  function chooseModel(id) {
    setModelId(id);
    savePref(MODEL_KEY, id);
  }

  // Tampilkan tombol "Balas" di atas teks yang diblok di dalam percakapan.
  function checkSelection() {
    const sel = window.getSelection();
    const text = sel?.toString().trim();
    if (!text || !sel.rangeCount || !bodyRef.current?.contains(sel.getRangeAt(0).commonAncestorContainer)) {
      setSelection(null);
      return;
    }
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    const host = chatRef.current.getBoundingClientRect();
    const above = rect.top - host.top - 42;
    setSelection({
      text,
      top: above > 60 ? above : rect.bottom - host.top + 8,
      left: Math.min(Math.max(rect.left + rect.width / 2 - host.left, 60), host.width - 60),
    });
  }

  useEffect(() => {
    const onChange = () => {
      if (!window.getSelection()?.toString().trim()) setSelection(null);
    };
    document.addEventListener("selectionchange", onChange);
    return () => document.removeEventListener("selectionchange", onChange);
  }, []);

  function replyToSelection() {
    const text = selection.text
      .replace(/[ \t]{2,}/g, " ")          // bekas posisi nomor rujukan
      .replace(/ +([.,;:!?])/g, "$1")
      .replace(/\n{3,}/g, "\n\n");
    setQuote(text.length > QUOTE_MAX ? `${text.slice(0, QUOTE_MAX)}…` : text);
    setSelection(null);
    window.getSelection()?.removeAllRanges();
    inputRef.current?.focus();
  }

  useEffect(() => {
    // Jangan di-return: di Chromium baru scrollIntoView() mengembalikan Promise,
    // dan React akan mencoba memanggilnya sebagai fungsi cleanup -> halaman crash.
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, view]);
  useEffect(() => () => abortRef.current?.abort(), []);

  function setConversation(id) {
    conversationId.current = id;
    setChatId(id);
    rememberChatId(id);
  }

  // Buka percakapan tersimpan (null = percakapan baru). `restoring`: dipanggil saat
  // halaman dibuka ulang -> jangan buang draf, kutipan, atau tampilan yang dipulihkan.
  async function openChat(id, restoring = false) {
    abortRef.current?.abort();
    setBusy(false);
    setResuming(null);
    setSelection(null);
    if (!restoring) {
      setView("chat");
      setQuote(null);
    }
    if (!id) {
      setConversation(null);
      setRefs(null);
      setMessages([]);
      return;
    }
    try {
      const chat = await getJSON(`/api/chats/${id}`);
      setConversation(chat.id);
      setRefs(chat.refs);
      setMessages(withPending(chat));
      setResuming(chat.pending ? chat.id : null);
    } catch {
      setConversation(null); // sudah dihapus / tidak ada
      setRefs(null);
      setMessages([]);
    }
  }

  // Lanjutkan percakapan terakhir setelah halaman di-refresh.
  useEffect(() => {
    const id = savedChatId();
    if (id) openChat(id, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Jawaban yang masih dibuat server (halaman dibuka ulang di tengah jawaban):
  // tampilkan teks sejauh ini dan perbarui sampai jawabannya selesai & tersimpan.
  useEffect(() => {
    if (!resuming) return;
    const timer = setInterval(() => {
      getJSON(`/api/chats/${resuming}`)
        .then((chat) => {
          setRefs(chat.refs);
          setMessages(withPending(chat));
          if (!chat.pending) setResuming(null);
        })
        .catch(() => setResuming(null));
    }, 1500);
    return () => clearInterval(timer);
  }, [resuming]);

  // Perbarui pesan AI terakhir (yang sedang dialirkan).
  const patchLast = (fn) =>
    setMessages((prev) => [...prev.slice(0, -1), fn(prev[prev.length - 1])]);

  async function send(question) {
    question = question.trim();
    if (!question || busy || resuming) return;
    if (quote) question = `${toQuoteBlock(quote)}\n\n${question}`;
    setQuote(null);
    setInput("");
    setBusy(true);
    setView("chat");
    setMessages((prev) => [...prev, { role: "user", text: question }, { role: "assistant", text: "" }]);
    abortRef.current = new AbortController();
    try {
      await streamChat({
        question,
        conversationId: conversationId.current,
        model: modelId,
        signal: abortRef.current.signal,
        onEvent: (event, data) => {
          if (event === "meta") {
            setConversation(data.conversation_id);
            setRefs((prev) => ({ ...prev, ...data.refs })); // jangan hilangkan rujukan jawaban lama
          }
          else if (event === "text") patchLast((m) => ({ ...m, text: m.text + data.text }));
          else if (event === "done") patchLast((m) => ({ ...m, sources: data.sources, usage: data.usage, model: data.model }));
          else if (event === "error") patchLast((m) => ({ ...m, error: data.message }));
        },
      });
    } catch (e) {
      if (e.name !== "AbortError") patchLast((m) => ({ ...m, error: e.message }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="chat" ref={chatRef}>
      <Resizer width={width} onResize={onResize} onReset={onResetWidth} />
      <div className="chat-head">
        <h2>Tanya AI</h2>
        <button className={`btn ${view === "history" ? "active" : ""}`}
          onClick={() => setView(view === "history" ? "chat" : "history")}>
          Riwayat
        </button>
        <button className="btn" onClick={() => openChat(null)} disabled={!messages.length && view === "chat"}>
          Percakapan baru
        </button>
        <button className="close" onClick={onClose} aria-label="Tutup">×</button>
      </div>

      {view === "history" ? (
        <div className="chat-body">
          <History activeId={chatId} onOpen={openChat} onBack={() => setView("chat")} />
        </div>
      ) : (
      <div
        className="chat-body"
        ref={bodyRef}
        onMouseUp={() => setTimeout(checkSelection, 0)}
        onKeyUp={() => setTimeout(checkSelection, 0)}
        onTouchEnd={() => setTimeout(checkSelection, 0)}
        onScroll={() => setSelection(null)}
      >
        {!ready && (
          <p className="notice error">
            {model?.reason ?? "Model belum siap."}{" "}
            {models.some((m) => m.available) && "Pilih model lain di bawah."}
          </p>
        )}
        {messages.length === 0 && ready && (
          <div className="suggestions">
            <p className="hint">Tanya apa saja tentang isi perpustakaanmu. Jawaban menyebut reel sumbernya.</p>
            {SUGGESTIONS.map((s) => (
              <button key={s} className="suggestion" onClick={() => send(s)}>{s}</button>
            ))}
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <UserMessage key={i} text={m.text} />
          ) : (
            <Answer key={i} msg={m} refs={refs} onOpenReel={onOpenReel} labelOf={labelOf} />
          ),
        )}
        <div ref={bottomRef} />
      </div>
      )}

      {selection && ready && (
        <button
          className="reply-btn"
          style={{ top: selection.top, left: selection.left }}
          onMouseDown={(e) => e.preventDefault()} // jangan hilangkan blok sebelum diklik
          onClick={replyToSelection}
        >
          ↩ Balas
        </button>
      )}

      {quote && (
        <div className="quote-preview">
          <div className="quote-preview-text">
            <strong>Membalas</strong>
            <span>{quote}</span>
          </div>
          <button className="close" onClick={() => setQuote(null)} aria-label="Batalkan balasan">×</button>
        </div>
      )}

      {models.length > 0 && (
        <div className="model-bar">
          <label htmlFor="chat-model">Model</label>
          <select id="chat-model" value={modelId ?? ""} onChange={(e) => chooseModel(e.target.value)}
            disabled={busy}>
            {[["anthropic", "Claude (berbayar)"], ["ollama", "Ollama (gratis)"]].map(([provider, group]) => {
              const list = models.filter((m) => m.provider === provider);
              return list.length > 0 && (
                <optgroup key={provider} label={group}>
                  {list.map((m) => (
                    <option key={m.id} value={m.id} disabled={!m.available}>
                      {m.label}{m.available ? "" : " (tidak tersedia)"}
                    </option>
                  ))}
                </optgroup>
              );
            })}
          </select>
          <span className="model-note" title={model?.reason || model?.note}>
            {model?.available ? model.note : model?.reason}
          </span>
        </div>
      )}

      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <textarea
          ref={inputRef}
          rows={2}
          placeholder={
            !ready ? "Model belum siap"
              : quote ? "Tulis balasan untuk kutipan di atas… (Esc batal)"
                : "Tulis pertanyaan… (Enter kirim, Shift+Enter baris baru)"
          }
          value={input}
          disabled={!ready}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape" && quote) {
              setQuote(null);
            } else if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
        />
        <button className="btn primary" disabled={!ready || busy || resuming || !input.trim()}>
          {busy || resuming ? "…" : "Kirim"}
        </button>
      </form>
    </aside>
  );
}
