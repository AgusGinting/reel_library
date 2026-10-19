"""Tanya jawab perpustakaan dengan model Ollama (lokal atau cloud, mis. gemma4:31b-cloud).

Memakai mode pencarian (retrieval.py): katalog semua judul + detail ±15 item paling
relevan, jadi jatah gratis tidak habis untuk mengirim seluruh perpustakaan tiap pertanyaan.
Antarmukanya sama dengan ask.Librarian (stream, answer, cited, usage, refs).
"""

import json
import re
import urllib.error
import urllib.request
from types import SimpleNamespace

import web_tools
from config import OLLAMA_URL
from retrieval import Retriever, search  # noqa: F401  (search dipakai skrip uji/CLI)


class OllamaError(RuntimeError):
    pass


class OllamaLibrarian:
    def __init__(self, model, model_id=None, refs=None, history=None):
        self.model = model
        self.model_id = model_id or model
        self.retriever = Retriever(refs)
        self.refs = self.retriever.refs
        self.system = self.retriever.system_prompt()
        # Riwayat disimpan sebagai teks pertanyaan & jawaban saja (tanpa <detail> lama).
        self.messages = [{"role": m["role"], "content": m["text"]} for m in history or []]
        self.count = len(self.refs)

    def _chat(self, messages, tools):
        """Satu panggilan /api/chat (streaming). Menghasilkan potongan teks (str), lalu
        terakhir dict {"tool_calls": [...], "final": {...}}."""
        payload = {"model": self.model, "stream": True, "think": False, "messages": messages}
        if tools:
            payload["tools"] = web_tools.ollama_tools()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        calls, final = [], {}
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                for line in resp:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise OllamaError(data["error"])
                    message = data.get("message") or {}
                    calls += message.get("tool_calls") or []
                    if message.get("content"):
                        yield message["content"]
                    if data.get("done"):
                        final = data
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("error", "")
            except ValueError:
                detail = ""
            raise OllamaError(f"Ollama {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError("Ollama tidak berjalan. Buka aplikasi Ollama lalu coba lagi.") from exc
        yield {"tool_calls": calls, "final": final}

    def stream(self, question, web=False):
        """Alirkan jawaban: str = potongan teks; dict {"tool": ...} = model memakai alat
        internet (hanya bila web=True). Setelah selesai mengisi answer, cited, web, usage."""
        previous = [m["content"] for m in self.messages if m["role"] == "user"]
        content = self.retriever.user_message(question, previous)
        system = self.system
        if web:
            # Petunjuk internet di DEPAN system prompt + catatan di pertanyaan (lihat TURN_NOTE).
            system = f"{web_tools.INSTRUCTIONS}\n\n{self.system}"
            content = f"{web_tools.TURN_NOTE}\n\n{content}"
        convo = [{"role": "system", "content": system}, *self.messages,
                 {"role": "user", "content": content}]
        self.web, texts, tokens_in, tokens_out = [], [], 0, 0

        for round_no in range(web_tools.MAX_ROUNDS + 1):
            allow = web and round_no < web_tools.MAX_ROUNDS
            parts, result = [], {}
            for chunk in self._chat(convo, tools=allow):
                if isinstance(chunk, dict):
                    result = chunk
                    continue
                if not parts and texts:
                    yield "\n\n"   # pisahkan teks dari putaran sebelumnya
                parts.append(chunk)
                yield chunk
            text = "".join(parts)
            if text.strip():
                texts.append(text)
            final = result.get("final") or {}
            tokens_in += final.get("prompt_eval_count", 0)
            tokens_out += final.get("eval_count", 0)
            calls = result.get("tool_calls") or []
            if not calls:
                break
            convo.append({"role": "assistant", "content": text, "tool_calls": calls})
            for call in calls:
                fn = call.get("function") or {}
                name, args = fn.get("name", ""), fn.get("arguments") or {}
                info = web_tools.describe(name, args if isinstance(args, dict) else {})
                self.web.append(info)
                yield {"tool": info}
                output = (web_tools.run_tool(name, args) if allow
                          else "ERROR: akses internet dimatikan oleh pengguna.")
                convo.append({"role": "tool", "content": output, "tool_name": name})

        self.answer = "\n\n".join(texts)
        # Riwayat hanya teks tanya-jawab (tanpa <detail> & hasil alat) agar tetap ringkas.
        self.messages += [{"role": "user", "content": question},
                          {"role": "assistant", "content": self.answer}]
        self.cited = [ref for ref in dict.fromkeys(re.findall(r"\[(R\d+)\]", self.answer))
                      if ref in self.refs]
        self.usage = SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out,
                                     cache_read_input_tokens=0, cache_creation_input_tokens=0)


def installed_models():
    """Nama model yang terdaftar di Ollama, atau None bila Ollama tidak berjalan."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as resp:
            return {m["name"] for m in json.loads(resp.read()).get("models", [])}
    except (urllib.error.URLError, OSError, ValueError):
        return None
