# -*- coding: utf-8 -*-
"""小红书 App 业务操作：启动、判断登录、搜索、翻页、打开笔记。"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import httpx

from .constants import (
    COMMENT_INPUT_HINTS,
    COPY_LINK_TEXT,
    LOGIN_ACTIVITY_MARKERS,
    LOGIN_HINT_TEXTS,
    SHARE_DESC_PREFIX,
    XHS_PACKAGE,
    XHS_SEARCH_RESULT_URI,
    XHS_SHORT_LINK_RE,
)
from .device import AdbDevice
from .hierarchy import SearchCard


@dataclass
class SearchSession:
    keyword: str
    logged_in: bool
    cards: list[SearchCard]
    opened_notes: list[dict]


class XhsAdbApp:
    """只通过官方 App UI / deeplink 操作，不复用 Web Cookie，也不打开放接口。"""

    def __init__(self, device: AdbDevice, output_dir: Optional[Path] = None) -> None:
        self.device = device
        self.output_dir = output_dir or Path("data/xhs/adb")
        self.search_intent_count = 0

    def launch_home(self) -> None:
        self.device.ensure_awake()
        self.device.shell(
            "monkey",
            "-p",
            XHS_PACKAGE,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
        time.sleep(2.0)
        self._dismiss_blocking_dialogs()

    def inspect_login(self) -> tuple[bool, str]:
        """
        返回 (是否已登录, 原因)。
        未登录时搜索列表通常仍可用，但点进笔记会被半屏登录拦住。
        """
        focus = self.device.current_focus()
        if any(marker in focus for marker in LOGIN_ACTIVITY_MARKERS):
            return False, f"当前页面是登录相关 Activity：{focus}"
        hierarchy = self.device.dump_ui()
        if hierarchy.has_any_text(LOGIN_HINT_TEXTS):
            return False, "页面出现掉线/去登录文案"
        return True, "未发现登录拦截"

    def search(self, keyword: str, pages: int = 2, open_count: int = 0) -> SearchSession:
        """用官方 deeplink 打开搜索结果，再按页滑动收集卡片。"""
        self._open_search(keyword)
        logged_in, _ = self.inspect_login()
        cards: list[SearchCard] = []
        seen: set[str] = set()
        for page in range(max(1, pages)):
            hierarchy = self.device.dump_ui()
            for card in hierarchy.extract_search_cards():
                key = f"{card.title}|{card.author}"
                if key in seen:
                    continue
                seen.add(key)
                cards.append(card)
            if page < pages - 1:
                self.device.swipe(610, 1900, 610, 720, 380)
                time.sleep(1.8)

        opened_notes: list[dict] = []
        if open_count > 0:
            if not logged_in:
                opened_notes.append({"skipped": True, "reason": "未登录，点进笔记会被半屏登录拦住"})
            else:
                # 若刚才为了收集列表滑走了，先回到顶部，之后只返回列表、不再重新搜索
                if pages > 1:
                    self.device.swipe(610, 720, 610, 1900, 380)
                    time.sleep(1.2)
                opened_notes = self._open_visible_notes(open_count)

        session = SearchSession(
            keyword=keyword,
            logged_in=logged_in,
            cards=cards,
            opened_notes=opened_notes,
        )
        self._persist(session)
        return session

    def _open_search(self, keyword: str) -> None:
        self.search_intent_count += 1
        self.device.ensure_awake()
        encoded = urllib.parse.quote(keyword)
        uri = XHS_SEARCH_RESULT_URI.format(keyword=encoded)
        self.device.shell(
            "am",
            "start",
            "-W",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            uri,
            XHS_PACKAGE,
        )
        time.sleep(2.4)
        self._dismiss_blocking_dialogs()

    def open_note(self, card: SearchCard) -> dict:
        self.device.tap(card.tap_x, card.tap_y)
        time.sleep(2.4)
        focus = self.device.current_focus()
        if any(marker in focus for marker in LOGIN_ACTIVITY_MARKERS):
            self.device.back()
            time.sleep(0.4)
            return {"title": card.title, "author": card.author, "blocked_by_login": True, "focus": focus}

        hierarchy = self.device.dump_ui()
        texts = [n.text for n in hierarchy.nodes if n.text]
        short_url = self._copy_note_short_link()
        note_url, note_id = self._expand_note_link(short_url)
        self._return_to_search_list()
        return {
            "title": card.title,
            "author": card.author,
            "likes": card.likes,
            "blocked_by_login": False,
            "focus": focus,
            "short_url": short_url,
            "note_url": note_url,
            "note_id": note_id,
            "texts": texts[:30],
        }

    def _copy_note_short_link(self) -> str:
        """详情页：分享 → 左滑 → 复制链接 → 粘贴到顶栏搜索框读出短链。"""
        hierarchy = self.device.dump_ui()
        share = next(
            (n for n in hierarchy.nodes if n.content_desc.startswith(SHARE_DESC_PREFIX) and n.clickable),
            None,
        )
        if share is None:
            return ""
        self.device.tap(share.cx, share.cy)
        time.sleep(1.2)
        copy = self._find_copy_link()
        if copy is None:
            self.device.swipe(1000, 2480, 220, 2480, 280)
            time.sleep(0.7)
            copy = self._find_copy_link()
        if copy is None:
            self.device.back()
            return ""
        self.device.tap(copy.cx, copy.cy)
        time.sleep(1.0)
        return self._read_link_from_comment_paste()

    def _read_link_from_search_paste(self) -> str:
        """评论框拿不到时的兜底：粘到顶栏搜索，随后靠返回键回到列表。"""
        self.device.tap(500, 230)
        time.sleep(0.4)
        hierarchy = self.device.dump_ui()
        clear = next(
            (n for n in hierarchy.nodes if n.content_desc == "全部删除" or n.text == "全部删除"),
            None,
        )
        if clear is not None:
            self.device.tap(clear.cx, clear.cy)
            time.sleep(0.25)
        self.device.shell("input", "keyevent", "KEYCODE_PASTE")
        time.sleep(0.7)
        hierarchy = self.device.dump_ui()
        blob = " ".join(n.text for n in hierarchy.nodes if n.text)
        matches = re.findall(XHS_SHORT_LINK_RE, blob)
        if not matches:
            return ""
        return matches[-1].rstrip("\\n").rstrip("/")

    def _find_copy_link(self):
        hierarchy = self.device.dump_ui()
        return next(
            (n for n in hierarchy.nodes if n.text == COPY_LINK_TEXT or n.content_desc == COPY_LINK_TEXT),
            None,
        )

    def _open_visible_notes(self, open_count: int) -> list[dict]:
        """在同一份搜索结果上连续点开笔记，看完只返回列表。"""
        opened: list[dict] = []
        seen: set[str] = set()
        idle_swipes = 0
        while len(opened) < open_count and idle_swipes < 6:
            if not self._on_search_list():
                self._return_to_search_list()
            visible = self.device.dump_ui().extract_search_cards()
            nxt = next((card for card in visible if f"{card.title}|{card.author}" not in seen), None)
            if nxt is None:
                self.device.swipe(610, 1900, 610, 720, 380)
                time.sleep(1.4)
                idle_swipes += 1
                continue
            idle_swipes = 0
            seen.add(f"{nxt.title}|{nxt.author}")
            note = self.open_note(nxt)
            opened.append(note)
            url = note.get("note_url") or note.get("short_url") or ""
            print(f"[{len(opened)}/{open_count}] {nxt.title[:32]} {url}", flush=True)
        return opened

    def _on_search_list(self) -> bool:
        focus = self.device.current_focus()
        if "DetailFeedActivity" in focus:
            return False
        if "GlobalSearchActivity" not in focus:
            return False
        hierarchy = self.device.dump_ui()
        if self._search_input_polluted(hierarchy):
            return False
        return bool(hierarchy.extract_search_cards())

    def _search_input_polluted(self, hierarchy) -> bool:
        if hierarchy.extract_search_cards():
            return False
        # 详情页评论框里也可能有刚粘贴的短链，不能当成搜索框污染
        if any(n.content_desc.startswith(SHARE_DESC_PREFIX) for n in hierarchy.nodes):
            return False
        if hierarchy.has_any_text(("相关搜索", "点赞", "收藏")):
            return False
        blob = " ".join(f"{n.text} {n.content_desc}" for n in hierarchy.nodes)
        return bool(re.search(XHS_SHORT_LINK_RE, blob)) or hierarchy.find_text("全部删除") is not None

    def _return_to_search_list(self) -> None:
        """从详情/键盘/搜索输入退回结果列表，不重新发搜索 Intent。"""
        for _ in range(6):
            focus = self.device.current_focus()
            hierarchy = self.device.dump_ui()
            if hierarchy.extract_search_cards() and "DetailFeedActivity" not in focus:
                return
            if "DetailFeedActivity" in focus:
                self.device.back()
                time.sleep(0.55)
                continue
            back_btn = hierarchy.find_text("返回")
            if self._search_input_polluted(hierarchy) and back_btn is not None:
                self.device.tap(back_btn.cx, back_btn.cy)
                time.sleep(0.7)
                continue
            self.device.back()
            time.sleep(0.45)

    def _read_link_from_comment_paste(self) -> str:
        """把短链粘到评论框再读出来，避免污染顶栏搜索、也不用重新搜。"""
        hierarchy = self.device.dump_ui()
        box = next(
            (n for n in hierarchy.nodes if n.text in COMMENT_INPUT_HINTS or n.content_desc in COMMENT_INPUT_HINTS),
            None,
        )
        if box is None:
            return ""
        self.device.tap(box.cx, box.cy)
        time.sleep(0.4)
        self.device.shell("input", "keyevent", "KEYCODE_PASTE")
        time.sleep(0.7)
        hierarchy = self.device.dump_ui()
        blob = " ".join(f"{n.text} {n.content_desc}" for n in hierarchy.nodes)
        matches = re.findall(XHS_SHORT_LINK_RE, blob)
        # 收起键盘，不发送评论
        self.device.back()
        time.sleep(0.35)
        if not matches:
            return ""
        return matches[-1].rstrip("\\n").rstrip("/")

    def _expand_note_link(self, short_url: str) -> tuple[str, str]:
        if not short_url:
            return "", ""
        try:
            with httpx.Client(follow_redirects=True, timeout=12.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
                response = client.get(short_url)
            final = str(response.url)
        except httpx.HTTPError:
            return short_url, ""
        if "website-login/error" in final:
            redirect = urllib.parse.parse_qs(urllib.parse.urlparse(final).query).get("redirectPath", [""])[0]
            if redirect:
                final = urllib.parse.unquote(redirect)
        note_id = ""
        item = re.search(r"/(?:discovery/item|explore)/([0-9a-f]+)", final)
        if item:
            note_id = item.group(1)
            token = urllib.parse.parse_qs(urllib.parse.urlparse(final).query).get("xsec_token", [""])[0]
            clean = f"https://www.xiaohongshu.com/explore/{note_id}"
            if token:
                clean = f"{clean}?xsec_token={urllib.parse.quote(token)}&xsec_source=app_share"
            return clean, note_id
        return final, ""

    def _dismiss_blocking_dialogs(self) -> None:
        focus = self.device.current_focus()
        if "NotificationShade" in focus:
            try:
                self.device.shell("cmd", "statusbar", "collapse")
            except Exception:
                self.device.swipe(610, 1800, 610, 200, 250)
            time.sleep(0.3)
        if any(marker in focus for marker in ("NotificationAuthorization",)):
            self.device.back()
            time.sleep(0.4)

    def _persist(self, session: SearchSession) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        day = date.today().isoformat()
        path = self.output_dir / f"search_{session.keyword}_{day}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            for card in session.cards:
                row = asdict(card)
                row["keyword"] = session.keyword
                row["logged_in"] = session.logged_in
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if session.opened_notes:
            detail_path = self.output_dir / f"detail_{session.keyword}_{day}.jsonl"
            with detail_path.open("a", encoding="utf-8") as fh:
                for note in session.opened_notes:
                    row = dict(note)
                    row["keyword"] = session.keyword
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return path
