# -*- coding: utf-8 -*-
"""解析 uiautomator dump 的 XML，提供按文本/描述查找与卡片抽取。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .constants import NOISE_TEXTS


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_LIKE_RE = re.compile(r"^(\d+(?:\.\d+)?万|\d+)$")
_DATE_RE = re.compile(r"^(?:\d+天前|\d+小时前|昨天|\d{4}-\d{2}-\d{2}|\d{2}-\d{2})$")


@dataclass(frozen=True)
class UiNode:
    text: str
    content_desc: str
    class_name: str
    clickable: bool
    bounds: tuple[int, int, int, int]

    @property
    def cx(self) -> int:
        x1, _, x2, _ = self.bounds
        return (x1 + x2) // 2

    @property
    def cy(self) -> int:
        _, y1, _, y2 = self.bounds
        return (y1 + y2) // 2

    @property
    def column(self) -> str:
        """双列瀑布流：左卡 / 右卡。"""
        return "left" if self.cx < 610 else "right"


@dataclass
class SearchCard:
    title: str
    author: str
    likes: str
    published: str
    column: str
    tap_x: int
    tap_y: int


class UiHierarchy:
    def __init__(self, nodes: list[UiNode]) -> None:
        self.nodes = nodes

    @classmethod
    def from_file(cls, path: Path) -> "UiHierarchy":
        root = ET.parse(path).getroot()
        nodes: list[UiNode] = []
        for raw in root.iter("node"):
            bounds = _parse_bounds(raw.attrib.get("bounds", ""))
            if bounds is None:
                continue
            nodes.append(
                UiNode(
                    text=(raw.attrib.get("text") or "").strip(),
                    content_desc=(raw.attrib.get("content-desc") or "").strip(),
                    class_name=raw.attrib.get("class") or "",
                    clickable=raw.attrib.get("clickable") == "true",
                    bounds=bounds,
                )
            )
        return cls(nodes)

    def has_any_text(self, markers: Iterable[str]) -> bool:
        blob = " ".join(f"{n.text} {n.content_desc}" for n in self.nodes)
        return any(marker in blob for marker in markers)

    def find_text(self, text: str) -> Optional[UiNode]:
        for node in self.nodes:
            if node.text == text or node.content_desc == text:
                return node
        return None

    def extract_search_cards(self) -> list[SearchCard]:
        """从搜索结果双列瀑布流抽出笔记卡片。"""
        texts = [
            n
            for n in self.nodes
            if n.text and n.text not in NOISE_TEXTS and n.class_name.endswith("TextView")
        ]
        titles = [n for n in texts if _is_title(n.text)]
        cards: list[SearchCard] = []
        used: set[int] = set()
        for title in titles:
            nearby = [
                n
                for n in texts
                if n is not title
                and n.column == title.column
                and 0 < n.bounds[1] - title.bounds[3] < 280
            ]
            author = next((n for n in nearby if not _LIKE_RE.match(n.text) and not _DATE_RE.match(n.text)), None)
            published = next((n for n in nearby if _DATE_RE.match(n.text)), None)
            likes = next((n for n in nearby if _LIKE_RE.match(n.text)), None)
            # 作者名有时也会超过 8 字；半截出屏的卡片可能没有赞/时间
            if likes is None and published is None and "#" not in title.text:
                continue
            cards.append(
                SearchCard(
                    title=title.text,
                    author=author.text if author else "",
                    likes=likes.text if likes else "",
                    published=published.text if published else "",
                    column=title.column,
                    tap_x=title.cx,
                    tap_y=max(title.bounds[1] - 180, title.cy - 200),
                )
            )
            used.add(id(title))
        return cards


def _parse_bounds(raw: str) -> Optional[tuple[int, int, int, int]]:
    matched = _BOUNDS_RE.fullmatch(raw)
    if not matched:
        return None
    return tuple(int(g) for g in matched.groups())  # type: ignore[return-value]


def _is_title(text: str) -> bool:
    if len(text) < 8:
        return False
    if _LIKE_RE.match(text) or _DATE_RE.match(text):
        return False
    return True
