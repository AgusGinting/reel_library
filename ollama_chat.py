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

    def stream(self, question):
        """Alirkan potongan teks jawaban; setelah selesai mengisi answer, cited, usage."""
        previous = [m["content"] for m in self.messages if m["role"] == "user"]
        payload = {
            "model": self.model,
            "stream": True,
            "think": False,
            "messages": [{"role": "system", "content": self.system}, *self.messages,
                         {"role": "user", "content": self.retriever.user_message(question, previous)}],
        }
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        parts, final = [], {}
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                for line in resp:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise OllamaError(data["error"])
                    chunk = (data.get("message") or {}).get("content") or ""
                    if chunk:
                        parts.append(chunk)
                        yield chunk
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

        self.answer = "".join(parts)
        self.messages += [{"role": "user", "content": question},
                          {"role": "assistant", "content": self.answer}]
        self.cited = [ref for ref in dict.fromkeys(re.findall(r"\[(R\d+)\]", self.answer))
                      if ref in self.refs]
        self.usage = SimpleNamespace(
            input_tokens=final.get("prompt_eval_count", 0),
            output_tokens=final.get("eval_count", 0),
            cache_read_input_tokens=0, cache_creation_input_tokens=0)


def installed_models():
    """Nama model yang terdaftar di Ollama, atau None bila Ollama tidak berjalan."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as resp:
            return {m["name"] for m in json.loads(resp.read()).get("models", [])}
    except (urllib.error.URLError, OSError, ValueError):
        return None
