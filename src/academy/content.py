"""The course catalogue the API validates against. The same courses.json the
site serves is copied into the Lambda bundle by scripts/build_lambda.sh."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

CONTENT_PATH = Path(os.environ.get("ACADEMY_CONTENT", str(Path(__file__).resolve().parent / "content" / "courses.json")))


@lru_cache(maxsize=1)
def courses() -> dict[str, dict]:
    data = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data["courses"]}


def course(course_id: str) -> dict | None:
    return courses().get(course_id)


def lesson_ids(course_id: str) -> set[str]:
    c = course(course_id)
    return {l["id"] for l in c["lessons"]} if c else set()


def file_entry(course_id: str, file_id: str) -> dict | None:
    c = course(course_id)
    if not c:
        return None
    return next((f for f in c.get("files", []) if f["id"] == file_id), None)
