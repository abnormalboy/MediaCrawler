# -*- coding: utf-8 -*-
"""
小红书 App ADB 标准流程。

整次任务只发一次搜索 Intent，之后都是：
打开笔记 → 分享复制链接 → 返回列表 → 下一条。
不走 Web Cookie，不批量打开放接口。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .device import AdbDevice, AdbError
from .hierarchy import SearchCard
from .xhs_app import SearchSession, XhsAdbApp


class PipelineStep(str, Enum):
    """标准流程步骤，方便日志和排障。"""

    CHECK_DEVICE = "1_检查设备"
    CHECK_LOGIN = "2_检查登录"
    SEARCH_ONCE = "3_搜索一次"
    COLLECT_LIST = "4_收集列表"
    BROWSE_NOTES = "5_打开笔记并取链"
    PERSIST = "6_落盘"


@dataclass
class PipelineResult:
    keyword: str
    logged_in: bool
    search_intent_count: int
    cards: list[SearchCard] = field(default_factory=list)
    opened_notes: list[dict] = field(default_factory=list)
    report_path: Optional[Path] = None
    list_path: Optional[Path] = None
    detail_path: Optional[Path] = None

    def to_session(self) -> SearchSession:
        return SearchSession(
            keyword=self.keyword,
            logged_in=self.logged_in,
            cards=self.cards,
            opened_notes=self.opened_notes,
        )


class XhsAdbPipeline:
    """
    标准编排器。

    步骤固定为：
    1. 检查 adb 设备并唤醒
    2. 打开小红书，判断是否登录
    3. 用官方 deeplink 搜索一次
    4. 解析当前列表（可下滑翻页，不再次搜索）
    5. 逐条打开：复制链接后只返回列表
    6. 写入 jsonl + markdown 报告
    """

    def __init__(
        self,
        device: Optional[AdbDevice] = None,
        output_dir: Optional[Path] = None,
        on_step: Optional[Callable[[PipelineStep, str], None]] = None,
    ) -> None:
        self.device = device or AdbDevice()
        self.app = XhsAdbApp(self.device, output_dir=output_dir)
        self.on_step = on_step or (lambda step, msg: print(f"[{step.value}] {msg}", flush=True))

    def run(self, keyword: str, pages: int = 1, open_count: int = 0) -> PipelineResult:
        if pages < 1 or pages > 5:
            raise ValueError("pages 必须在 1-5 之间")
        if open_count < 0 or open_count > 10:
            raise ValueError("open_count 必须在 0-10 之间")

        self._step(PipelineStep.CHECK_DEVICE, "检查 adb 设备")
        self._check_device()

        self._step(PipelineStep.CHECK_LOGIN, "唤醒并检查登录态")
        self.app.device.ensure_awake()
        self.app.launch_home()
        logged_in, reason = self.app.inspect_login()
        self._step(PipelineStep.CHECK_LOGIN, f"logged_in={logged_in} {reason}")

        self._step(PipelineStep.SEARCH_ONCE, f"deeplink 搜索「{keyword}」")
        self.app._open_search(keyword)
        if self.app.search_intent_count != 1:
            raise RuntimeError(f"搜索 Intent 次数异常：{self.app.search_intent_count}")

        self._step(PipelineStep.COLLECT_LIST, f"收集列表，下滑 {pages} 屏")
        cards = self._collect_list(pages)

        opened_notes: list[dict] = []
        if open_count > 0:
            if not logged_in:
                opened_notes.append({"skipped": True, "reason": "未登录，点进笔记会被半屏登录拦住"})
                self._step(PipelineStep.BROWSE_NOTES, "未登录，只保留列表")
            else:
                if pages > 1:
                    self.app.device.swipe(610, 720, 610, 1900, 380)
                    time.sleep(1.2)
                self._step(PipelineStep.BROWSE_NOTES, f"打开 {open_count} 条，看完返回列表")
                opened_notes = self.app._open_visible_notes(open_count)

        result = PipelineResult(
            keyword=keyword,
            logged_in=logged_in,
            search_intent_count=self.app.search_intent_count,
            cards=cards,
            opened_notes=opened_notes,
        )
        self._step(PipelineStep.PERSIST, "写入 jsonl 与报告")
        self._persist(result)
        return result

    def _check_device(self) -> None:
        output = self.device.run("devices")
        online = [
            line
            for line in output.splitlines()[1:]
            if line.strip() and line.split()[-1] == "device"
        ]
        if not online:
            raise AdbError("没有可用的 adb 设备，请先 adb devices 确认已连接")

    def _collect_list(self, pages: int) -> list[SearchCard]:
        cards: list[SearchCard] = []
        seen: set[str] = set()
        for page in range(pages):
            for card in self.app.device.dump_ui().extract_search_cards():
                key = f"{card.title}|{card.author}"
                if key in seen:
                    continue
                seen.add(key)
                cards.append(card)
            if page < pages - 1:
                self.app.device.swipe(610, 1900, 610, 720, 380)
                time.sleep(1.8)
        return cards

    def _persist(self, result: PipelineResult) -> None:
        session = result.to_session()
        result.list_path = self.app._persist(session)
        day = date.today().isoformat()
        output_dir = self.app.output_dir
        if result.opened_notes:
            result.detail_path = output_dir / f"detail_{result.keyword}_{day}.jsonl"
        result.report_path = self._write_report(result, day)

    def _write_report(self, result: PipelineResult, day: str) -> Path:
        path = self.app.output_dir / f"report_{result.keyword}_{day}.md"
        lines = [
            f"# 小红书 ADB 搜索报告 · {result.keyword}",
            "",
            f"- 日期：{day}",
            f"- 登录：{result.logged_in}",
            f"- 搜索次数：{result.search_intent_count}（标准流程应为 1）",
            f"- 列表卡片：{len(result.cards)}",
            f"- 已打开：{len([n for n in result.opened_notes if not n.get('skipped')])}",
            "",
            "## 笔记链接",
            "",
        ]
        index = 1
        for note in result.opened_notes:
            if note.get("skipped"):
                lines.append(f"- 跳过：{note.get('reason')}")
                continue
            title = (note.get("title") or "无标题").replace("\n", " ")
            url = note.get("note_url") or note.get("short_url") or "（未拿到链接）"
            lines.append(f"{index}. {title}")
            lines.append(f"   {url}")
            if note.get("short_url") and note.get("note_url"):
                lines.append(f"   短链：{note['short_url']}")
            index += 1
        if not result.opened_notes:
            lines.append("本次未打开详情，仅收集了列表卡片。")
            for i, card in enumerate(result.cards, 1):
                lines.append(f"{i}. {card.title} | {card.author} | 赞:{card.likes}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _step(self, step: PipelineStep, message: str) -> None:
        self.on_step(step, message)
