"""Knowledge index for the TLG automation project.

Sources, all inside the repo:
  - Markdown: README.md, docs/*.md, knowledge/*.md, persona/*.md
  - Salon data: terraform/salon.auto.tfvars (hand-written, parsed with python-hcl2)
    and terraform/fresha-menu.auto.tfvars.json (staff and services, generated
    from Fresha by the menu sync)

Retrieval is BM25 over heading-sized chunks plus structured lookups on the
salon data. The corpus is a few hundred chunks, so lexical search is exact,
fast and needs no model or API key. Swap `_rank` for an embedding search if
the corpus ever grows past what BM25 handles well.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import hcl2
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parent.parent
DOC_GLOBS = ["README.md", "docs/*.md", "knowledge/*.md", "persona/*.md"]
SALON_TFVARS = Path("terraform") / "salon.auto.tfvars"
MENU_JSON = Path("terraform") / "fresha-menu.auto.tfvars.json"


@dataclass(frozen=True)
class Chunk:
    source: str   # repo-relative path, or "terraform/salon.auto.tfvars#services"
    heading: str
    text: str
    kind: str     # doc | service | staff | salon


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _people(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " or " + names[-1]


def chunk_markdown(path: Path, root: Path) -> list[Chunk]:
    rel = path.relative_to(root).as_posix()
    chunks: list[Chunk] = []
    heading = path.stem
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            chunks.append(Chunk(rel, heading, body, "doc"))
        buf.clear()

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip() or heading
        else:
            buf.append(line)
    flush()
    return chunks


def load_salon(root: Path) -> dict:
    with open(root / SALON_TFVARS, encoding="utf-8") as fh:
        data = hcl2.load(fh)
    salon = data["salon"]
    menu_path = root / MENU_JSON
    if menu_path.exists():
        menu = json.loads(menu_path.read_text(encoding="utf-8"))
        staff, services = menu["staff"], menu["services"]
    else:  # older layout: everything in the tfvars file
        staff, services = data["staff"], data["services"]
    return {"salon": salon, "staff": staff, "services": services}


def service_text(s: dict) -> str:
    line = f"{s['category']} | {s['name']}: {s['price']}, {s['duration']}"
    if s.get("staff"):
        line += f", with {_people(s['staff'])}"
    if s.get("notes"):
        line += f" ({s['notes']})"
    return line


class KnowledgeIndex:
    def __init__(self, root: Path = ROOT) -> None:
        self.root = root
        self.reload()

    # ----- build -----------------------------------------------------------

    def reload(self) -> dict:
        self.salon = load_salon(self.root)
        self.chunks: list[Chunk] = []
        for pattern in DOC_GLOBS:
            for path in sorted(self.root.glob(pattern)):
                self.chunks.extend(chunk_markdown(path, self.root))
        src = SALON_TFVARS.as_posix()
        menu_src = MENU_JSON.as_posix() if (self.root / MENU_JSON).exists() else src
        for s in self.salon["services"]:
            self.chunks.append(Chunk(f"{menu_src}#services", s["category"], service_text(s), "service"))
        for slug, m in self.salon["staff"].items():
            text = f"{m['name']}, {m['role']}. Bookable for: {', '.join(m.get('services', []))}."
            if m.get("booking_link"):
                text += f" Booking link: {m['booking_link']}"
            self.chunks.append(Chunk(f"{menu_src}#staff.{slug}", m["name"], text, "staff"))
        sal = self.salon["salon"]
        hours = "; ".join(f"{d}: {h}" for d, h in sal["opening_hours"].items())
        self.chunks.append(Chunk(f"{src}#salon", sal["name"],
                                 f"{sal['name']}, {sal['address']}, {sal['phone']}. Hours: {hours}. "
                                 f"General booking link: {sal['general_booking_link']}. {sal.get('extra_notes', '')}",
                                 "salon"))
        self._bm25 = BM25Okapi([_tokens(f"{c.heading} {c.text}") for c in self.chunks])
        return self.stats()

    def stats(self) -> dict:
        by_kind: dict[str, int] = {}
        for c in self.chunks:
            by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
        return {"chunks": len(self.chunks), "by_kind": by_kind,
                "sources": sorted({c.source.split("#")[0] for c in self.chunks})}

    # ----- retrieval ---------------------------------------------------------

    def search(self, query: str, limit: int = 5) -> list[dict]:
        q = _tokens(query)
        if not q:
            return []
        scores = self._bm25.get_scores(q)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in order[:limit]:
            if scores[i] <= 0:
                break
            out.append({**asdict(self.chunks[i]), "score": round(float(scores[i]), 3)})
        return out

    def find_services(self, query: str, limit: int = 20) -> list[dict]:
        q = query.casefold().strip()
        qt = set(_tokens(query))
        scored = []
        for s in self.salon["services"]:
            hay = f"{s['name']} {s['category']} {s.get('notes', '')}".casefold()
            ht = set(_tokens(hay))
            score = 0.0
            if q and q in s["name"].casefold():
                score += 10
            if q and q in hay:
                score += 3
            score += len(qt & ht)
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda t: (-t[0], t[1]["category"], t[1]["name"]))
        return [dict(s) for _, s in scored[:limit]]

    def who_does(self, service_name: str) -> list[dict]:
        hits = self.find_services(service_name, limit=10)
        return [{"service": s["name"], "category": s["category"], "price": s["price"],
                 "staff": s.get("staff", [])} for s in hits]

    def team_member(self, name: str) -> dict | None:
        n = name.casefold().strip()
        for slug, m in self.salon["staff"].items():
            if n in (slug, m["name"].casefold()):
                does = [f"{s['category']} | {s['name']}" for s in self.salon["services"]
                        if m["name"] in s.get("staff", [])]
                return {"slug": slug, **m, "service_count": len(does), "does": does}
        return None

    def team(self) -> list[dict]:
        return [{"slug": slug, "name": m["name"], "role": m["role"],
                 "categories": m.get("services", []), "booking_link": m.get("booking_link", "")}
                for slug, m in self.salon["staff"].items()]

    def salon_facts(self) -> dict:
        return dict(self.salon["salon"])

    def categories(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.salon["services"]:
            out[s["category"]] = out.get(s["category"], 0) + 1
        return out

    def read_source(self, rel_path: str) -> str:
        path = (self.root / rel_path).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("path must be inside the repo")
        if path.suffix not in {".md", ".tfvars", ".tf", ".py", ".json", ".txt"}:
            raise ValueError("unsupported file type")
        return path.read_text(encoding="utf-8")
