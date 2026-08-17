# -*- coding: utf-8 -*-
"""
小红书 App ADB 标准流程入口。

用法：
  uv run python tools/xhs_adb.py status
  uv run python tools/xhs_adb.py search -k 吧唧 -p 1 --open 5
  ./scripts/xhs_adb_search.sh 吧唧 5
"""

from __future__ import annotations

from typing import Optional

import typer

from adb_xhs import AdbDevice, XhsAdbApp
from adb_xhs.pipeline import XhsAdbPipeline

app = typer.Typer(add_completion=False, help="小红书 App ADB 标准流程：搜索一次，打开笔记，复制链接，返回列表")


@app.command()
def status(serial: Optional[str] = typer.Option(None, "--serial", "-s", help="adb devices 里的序列号")) -> None:
    """看设备是否在线、小红书是否已登录。"""
    device = AdbDevice(serial=serial)
    xhs = XhsAdbApp(device)
    xhs.launch_home()
    logged_in, reason = xhs.inspect_login()
    typer.echo(f"focus: {device.current_focus()}")
    typer.echo(f"logged_in: {logged_in}")
    typer.echo(f"reason: {reason}")


@app.command()
def search(
    keyword: str = typer.Option("吧唧", "--keyword", "-k", help="搜索词"),
    pages: int = typer.Option(1, "--pages", "-p", help="向下滑动页数，建议 1-3"),
    open_count: int = typer.Option(0, "--open", help="已登录时打开前 N 条并取链接，0-10"),
    serial: Optional[str] = typer.Option(None, "--serial", "-s"),
) -> None:
    """执行标准流程：搜索一次 → 打开 → 复制链接 → 返回列表。"""
    device = AdbDevice(serial=serial)
    pipeline = XhsAdbPipeline(device=device)
    result = pipeline.run(keyword=keyword, pages=pages, open_count=open_count)
    typer.echo(
        f"keyword={result.keyword} logged_in={result.logged_in} "
        f"cards={len(result.cards)} search_intents={result.search_intent_count}"
    )
    for index, card in enumerate(result.cards, 1):
        typer.echo(f"{index:02d}. {card.title[:40]} | {card.author} | 赞:{card.likes} | {card.published}")
    for note in result.opened_notes:
        title = (note.get("title") or "")[:36]
        url = note.get("note_url") or note.get("short_url") or ""
        typer.echo(f"- {title}")
        typer.echo(f"  {url}")
    if result.report_path:
        typer.echo(f"report: {result.report_path}")


if __name__ == "__main__":
    app()
