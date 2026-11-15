# Drives the real app (served on localhost:8080) in headless Chromium: screenshots plus a screen recording.
# Usage: python record_app.py <screenshot dir> <video dir>   (needs: pip install playwright)
import sys, time
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]; VID = sys.argv[2]
import os
CH = os.environ.get("CHROME")  # optional path to a Chromium binary; None uses Playwright's own
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CH)
    ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=VID, record_video_size={"width": 1280, "height": 720})
    pg = ctx.new_page()
    pg.goto("http://localhost:8080/"); pg.wait_for_selector(".preset"); time.sleep(1)
    pg.get_by_role("button", name="RW Aurigae").click(); time.sleep(0.6)
    pg.get_by_role("button", name="1. Search archive").click(); pg.wait_for_selector("text=Archive search", timeout=180000); time.sleep(1.5)
    pg.screenshot(path=f"{OUT}/01_search.png")
    pg.get_by_role("button", name="2. Analyze epochs").click(); pg.wait_for_selector("text=Valid comparisons", timeout=600000); time.sleep(2)
    pg.screenshot(path=f"{OUT}/02_summary.png")
    pg.locator(".timeline").scroll_into_view_if_needed(); time.sleep(0.5)
    pg.get_by_role("button", name="Play usable epochs in time order").click(); time.sleep(4)
    pg.screenshot(path=f"{OUT}/03_playback.png")
    pg.get_by_role("button", name="Pause").click()
    pg.locator(".grid4").scroll_into_view_if_needed(); time.sleep(3)
    pg.screenshot(path=f"{OUT}/04_comparison.png")
    pg.evaluate("window.scrollTo(0,0)"); time.sleep(0.5)
    pg.get_by_role("button", name="Barnard's Star").click(); time.sleep(0.5)
    pg.get_by_role("button", name="2. Analyze epochs").click(); pg.wait_for_selector("text=No valid comparison", timeout=600000); time.sleep(1)
    pg.locator(".refuse").scroll_into_view_if_needed(); time.sleep(2)
    pg.screenshot(path=f"{OUT}/05_refusal.png")
    pg.locator(".epoch").scroll_into_view_if_needed(); time.sleep(2)
    pg.screenshot(path=f"{OUT}/06_rejected_epoch.png")
    ctx.close(); b.close()
