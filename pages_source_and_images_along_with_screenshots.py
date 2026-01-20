#!/usr/bin/env python3
"""
ADP Batch Page Scraper v4 - With Detailed Logging
--------------------------------------------------
Reads URLs from Excel file and processes each page with full logging.

Output Structure:
  DOMFolder/
    {Data_Segment}__{page-name}/
      {page-name}_dom.html
      {page-name}_mapping.json
      images/
      screenshots/
    batch_report.json
    scraper.log

Requirements:
    pip install playwright pandas openpyxl requests Pillow
    playwright install chromium

Usage:
    python adp_batch_scraper.py [excel_file]
"""

import os
import sys
import time
import json
import re
import hashlib
import logging
import traceback
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright, Page, Error as PlaywrightError

# ===================== CONFIG =====================
DEFAULT_EXCEL = "./Book001.xlsx"
OUTPUT_BASE = Path("./DOMFolder").resolve()
TIMEOUT_MS = 60000
WAIT_AFTER_LOAD = 4.0
WAIT_AFTER_CLICK = 1.0
IMAGE_DOWNLOAD_TIMEOUT = 30
MAX_RETRIES = 2
DEBUG_SCREENSHOTS = True

# Screenshot compression settings
SCREENSHOT_FORMAT = "jpeg"  # "jpeg" or "png" - jpeg is much smaller
SCREENSHOT_QUALITY = 75  # JPEG quality (1-100), 75 is good balance
SCREENSHOT_MAX_WIDTH = 1280  # Resize if wider (None to disable)
SCREENSHOT_MAX_HEIGHT = None  # Max height for scroll screenshots (None for no limit)
SCREENSHOT_FULL_PAGE_MAX_HEIGHT = 15000  # Max height for stitched full page


# ==================================================


def setup_logging(output_dir: Path) -> logging.Logger:
    """Setup logging to both file and console."""
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger('ADPScraper')
    logger.setLevel(logging.DEBUG)

    # Clear existing handlers
    logger.handlers = []

    # File handler - detailed
    file_handler = logging.FileHandler(output_dir / 'scraper.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(file_format)

    # Console handler - info level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_format)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Global logger
log = None


def sanitize_filename(name: str) -> str:
    """Convert string to safe filename."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')
    return name[:80]


def get_page_name_from_url(url: str) -> str:
    """Extract meaningful name from URL path."""
    parsed = urlparse(url)
    path = parsed.path
    name = path.rstrip('/').split('/')[-1]
    name = re.sub(r'\.(aspx|html|htm|php)$', '', name, flags=re.IGNORECASE)
    if not name:
        name = parsed.netloc.replace('.', '_')
    return sanitize_filename(name)


def create_output_folder(data_segment: str, url: str, base_dir: Path) -> Path:
    """Create output folder: DOMFolder/{Data_Segment}__{page-name}/"""
    segment = sanitize_filename(data_segment)
    page_name = get_page_name_from_url(url)
    folder_name = f"{segment}__{page_name}"
    folder_path = base_dir / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    log.debug(f"Created output folder: {folder_path}")
    return folder_path


def verify_page_has_body(page: Page) -> tuple:
    """Check if the page has actual body content. Returns (bool, length)."""
    try:
        body_length = page.evaluate("""() => {
            const body = document.body;
            if (!body) return 0;
            return body.innerHTML.length;
        }""")
        return body_length > 500, body_length
    except Exception as e:
        log.error(f"Error checking body content: {str(e)}")
        return False, 0


def wait_for_page_content(page: Page, timeout: int = 20) -> bool:
    """Wait for the page to have actual body content."""
    log.debug(f"Waiting for page content (timeout: {timeout}s)...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        has_body, length = verify_page_has_body(page)
        if has_body:
            log.debug(f"Page content loaded: {length:,} bytes")
            return True
        time.sleep(0.5)

    log.warning(f"Timeout waiting for page content after {timeout}s")
    return False


def dismiss_cookie_banner(page: Page) -> bool:
    """Handle cookie consent banners."""
    log.debug("Looking for cookie banners...")

    cookie_selectors = [
        ("#onetrust-accept-btn-handler", "OneTrust Accept"),
        ("button:has-text('Accept and Continue')", "Accept and Continue"),
        ("button:has-text('Accept All')", "Accept All"),
        ("button:has-text('Accept Cookies')", "Accept Cookies"),
        ("button:has-text('I Accept')", "I Accept"),
        ("button:has-text('Got it')", "Got it"),
    ]

    for selector, name in cookie_selectors:
        try:
            log.debug(f"  Trying cookie selector: {name}")
            btn = page.locator(selector).first
            if btn.is_visible(timeout=800):
                log.info(f"        → Found cookie banner: {name}")
                btn.click()
                time.sleep(0.5)
                log.info(f"        ✓ Accepted cookies via: {name}")
                return True
        except PlaywrightError as e:
            log.debug(f"  Selector '{name}' not found or not clickable: {str(e)[:50]}")
        except Exception as e:
            log.debug(f"  Error with selector '{name}': {type(e).__name__}: {str(e)[:50]}")

    log.debug("No cookie banner found")
    return False


def handle_employee_popup(page: Page) -> bool:
    """Handle ADP's employee count selection popup."""
    log.debug("Looking for employee count popup...")

    selectors = [
        ("button:has-text('1-49 Employees')", "1-49 Employees"),
        ("button:has-text('6-49 Employees')", "6-49 Employees"),
        ("button:has-text('1-5 Employees')", "1-5 Employees"),
        ("button:has-text('50-999 Employees')", "50-999 Employees"),
        ("button:has-text('1000+ Employees')", "1000+ Employees"),
        ("button:has-text('50+ Employees')", "50+ Employees"),
    ]

    for selector, name in selectors:
        try:
            log.debug(f"  Trying employee selector: {name}")
            btn = page.locator(selector).first

            if btn.is_visible(timeout=600):
                log.debug(f"  Found visible button: {name}")

                # Verify it's inside a modal
                try:
                    is_in_modal = btn.evaluate("""el => {
                        const parent = el.closest('[role="dialog"], .modal, [class*="modal"], [class*="popup"], [class*="overlay"], [class*="interstitial"]');
                        return parent !== null;
                    }""")
                    log.debug(f"  Button in modal: {is_in_modal}")
                except Exception as e:
                    log.debug(f"  Could not check if in modal: {str(e)[:30]}")
                    is_in_modal = True  # Assume yes

                if is_in_modal:
                    btn_text = btn.text_content() or name
                    log.info(f"        → Found employee popup")
                    btn.click()
                    time.sleep(1.5)
                    log.info(f"        ✓ Selected: {btn_text.strip()[:30]}")
                    return True
                else:
                    log.debug(f"  Button '{name}' not in modal, skipping")

        except PlaywrightError as e:
            log.debug(f"  Playwright error for '{name}': {str(e)[:50]}")
        except Exception as e:
            log.debug(f"  Error with '{name}': {type(e).__name__}: {str(e)[:50]}")

    log.debug("No employee popup found")
    return False


def close_modal_buttons(page: Page) -> bool:
    """Try to close modals using close buttons."""
    log.debug("Looking for modal close buttons...")

    close_selectors = [
        ("button[aria-label*='close' i]", "aria-label close"),
        ("button[aria-label*='Close' i]", "aria-label Close"),
        ("button[class*='close']", "class close"),
        (".modal button.close", "modal button.close"),
        ("[role='dialog'] button:has(svg)", "dialog svg button"),
        ("button:has-text('×')", "× button"),
        ("button:has-text('✕')", "✕ button"),
    ]

    for selector, name in close_selectors:
        try:
            log.debug(f"  Trying close selector: {name}")
            buttons = page.locator(selector)
            count = buttons.count()
            log.debug(f"  Found {count} matching elements")

            for i in range(min(count, 3)):
                try:
                    btn = buttons.nth(i)
                    if btn.is_visible(timeout=400):
                        box = btn.bounding_box()
                        log.debug(f"  Button {i} bounding box: {box}")

                        if box and box['width'] < 80 and box['height'] < 80:
                            # Check if in modal
                            try:
                                is_in_modal = btn.evaluate("""el => {
                                    const modal = el.closest('[role="dialog"], .modal, [class*="modal"]');
                                    return modal !== null;
                                }""")
                            except:
                                is_in_modal = True

                            if is_in_modal:
                                log.info(f"        → Found close button: {name}")
                                btn.click()
                                time.sleep(0.5)
                                log.info(f"        ✓ Closed modal via: {name}")
                                return True
                            else:
                                log.debug(f"  Close button not in modal")
                except Exception as e:
                    log.debug(f"  Error with button {i}: {str(e)[:40]}")

        except Exception as e:
            log.debug(f"  Error with selector '{name}': {type(e).__name__}: {str(e)[:50]}")

    log.debug("No modal close button found")
    return False


def close_chat_widget(page: Page) -> bool:
    """Close chat widget if present."""
    log.debug("Looking for chat widget...")

    chat_selectors = [
        "[class*='chat'] button[class*='close']",
        "[id*='chat'] button[class*='close']",
        "[class*='chat'] [aria-label*='close' i]",
        ".chat-close",
    ]

    for selector in chat_selectors:
        try:
            log.debug(f"  Trying chat selector: {selector[:40]}")
            btn = page.locator(selector).first
            if btn.is_visible(timeout=400):
                log.info(f"        → Found chat widget")
                btn.click()
                time.sleep(0.3)
                log.info(f"        ✓ Closed chat widget")
                return True
        except Exception as e:
            log.debug(f"  Chat selector error: {str(e)[:40]}")

    log.debug("No chat widget found")
    return False


def remove_overlays_js(page: Page) -> int:
    """Remove overlay elements via JavaScript."""
    log.debug("Removing overlays via JavaScript...")

    try:
        removed = page.evaluate("""() => {
            let count = 0;

            // Modal backdrops
            document.querySelectorAll('.modal-backdrop, [class*="backdrop"]').forEach(el => {
                el.remove();
                count++;
            });

            // Cookie banners
            document.querySelectorAll('#onetrust-banner-sdk, [class*="cookie-banner"], [class*="cookie-consent"]').forEach(el => {
                el.remove();
                count++;
            });

            // Reset body scroll
            document.body.style.overflow = '';
            document.body.style.position = '';
            document.documentElement.style.overflow = '';

            return count;
        }""")

        if removed > 0:
            log.info(f"        → Removed {removed} overlay elements via JS")
        else:
            log.debug("No overlays removed via JS")

        return removed

    except Exception as e:
        log.error(f"Error removing overlays: {type(e).__name__}: {str(e)}")
        return 0


def handle_all_popups(page: Page, output_dir: Path = None) -> dict:
    """Handle all popups carefully. Returns detailed stats."""
    log.info("    [POPUPS] Starting popup handling...")

    stats = {
        'cookie_dismissed': False,
        'employee_popup_handled': False,
        'modals_closed': 0,
        'chat_closed': False,
        'overlays_removed': 0,
        'total_handled': 0,
        'errors': []
    }

    # Debug screenshot before
    if DEBUG_SCREENSHOTS and output_dir:
        try:
            screenshot_path = output_dir / "debug_1_before_popups.png"
            page.screenshot(path=str(screenshot_path))
            log.debug(f"Saved debug screenshot: {screenshot_path.name}")
        except Exception as e:
            log.debug(f"Could not save debug screenshot: {str(e)[:40]}")

    # 1. Cookie banner
    log.info("    [POPUPS] Step 1: Cookie banner")
    try:
        if dismiss_cookie_banner(page):
            stats['cookie_dismissed'] = True
            stats['total_handled'] += 1
            time.sleep(0.5)
    except Exception as e:
        error_msg = f"Cookie banner error: {type(e).__name__}: {str(e)}"
        log.error(f"        ✗ {error_msg}")
        stats['errors'].append(error_msg)

    # 2. Escape key
    log.info("    [POPUPS] Step 2: Pressing Escape key")
    try:
        page.keyboard.press("Escape")
        time.sleep(0.3)
        log.debug("Pressed Escape key")
    except Exception as e:
        log.debug(f"Escape key error: {str(e)[:40]}")

    # 3. Employee popup (multiple attempts)
    log.info("    [POPUPS] Step 3: Employee count popup")
    for attempt in range(3):
        try:
            if handle_employee_popup(page):
                stats['employee_popup_handled'] = True
                stats['total_handled'] += 1
                time.sleep(1.0)
            else:
                break
        except Exception as e:
            error_msg = f"Employee popup error (attempt {attempt + 1}): {type(e).__name__}: {str(e)}"
            log.error(f"        ✗ {error_msg}")
            stats['errors'].append(error_msg)
            break

    # 4. Modal close buttons
    log.info("    [POPUPS] Step 4: Modal close buttons")
    for attempt in range(3):
        try:
            if close_modal_buttons(page):
                stats['modals_closed'] += 1
                stats['total_handled'] += 1
                time.sleep(0.5)
            else:
                break
        except Exception as e:
            error_msg = f"Modal close error (attempt {attempt + 1}): {type(e).__name__}: {str(e)}"
            log.error(f"        ✗ {error_msg}")
            stats['errors'].append(error_msg)
            break

    # 5. Chat widget
    log.info("    [POPUPS] Step 5: Chat widget")
    try:
        if close_chat_widget(page):
            stats['chat_closed'] = True
            stats['total_handled'] += 1
    except Exception as e:
        error_msg = f"Chat widget error: {type(e).__name__}: {str(e)}"
        log.error(f"        ✗ {error_msg}")
        stats['errors'].append(error_msg)

    # 6. Clean overlays via JS
    log.info("    [POPUPS] Step 6: JS overlay cleanup")
    try:
        stats['overlays_removed'] = remove_overlays_js(page)
        stats['total_handled'] += stats['overlays_removed']
    except Exception as e:
        error_msg = f"JS overlay error: {type(e).__name__}: {str(e)}"
        log.error(f"        ✗ {error_msg}")
        stats['errors'].append(error_msg)

    # Debug screenshot after
    if DEBUG_SCREENSHOTS and output_dir:
        try:
            screenshot_path = output_dir / "debug_2_after_popups.png"
            page.screenshot(path=str(screenshot_path))
            log.debug(f"Saved debug screenshot: {screenshot_path.name}")
        except Exception as e:
            log.debug(f"Could not save debug screenshot: {str(e)[:40]}")

    log.info(f"    [POPUPS] Complete - Total handled: {stats['total_handled']}, Errors: {len(stats['errors'])}")
    return stats


def expand_accordions(page: Page) -> dict:
    """Expand all accordion/FAQ sections."""
    log.info("    [ACCORDIONS] Expanding accordions/FAQ sections...")

    stats = {
        'found': 0,
        'expanded': 0,
        'already_expanded': 0,
        'errors': []
    }

    accordion_selectors = [
        (".js-accordion__header", "js-accordion__header"),
        (".aria-accordion__header", "aria-accordion__header"),
        ("[data-toggle='collapse']", "data-toggle collapse"),
        ("[data-bs-toggle='collapse']", "data-bs-toggle collapse"),
        (".accordion-button", "accordion-button"),
        ("button[aria-expanded='false']", "aria-expanded false"),
        (".faq-question", "faq-question"),
    ]

    for selector, name in accordion_selectors:
        try:
            log.debug(f"  Trying accordion selector: {name}")
            headers = page.locator(selector)
            count = headers.count()

            if count > 0:
                log.debug(f"  Found {count} elements with selector: {name}")
                stats['found'] += count

            for i in range(count):
                try:
                    header = headers.nth(i)
                    if header.is_visible(timeout=300):
                        expanded_attr = header.get_attribute("aria-expanded")

                        if expanded_attr == "true":
                            stats['already_expanded'] += 1
                            log.debug(f"  Accordion {i} already expanded")
                        else:
                            header_text = (header.text_content() or "").strip()[:40]
                            log.debug(f"  Clicking accordion {i}: {header_text}")
                            header.click()
                            stats['expanded'] += 1
                            time.sleep(0.2)

                except Exception as e:
                    error_msg = f"Accordion {i} error: {type(e).__name__}: {str(e)[:40]}"
                    log.debug(f"  {error_msg}")
                    stats['errors'].append(error_msg)

        except Exception as e:
            log.debug(f"  Selector '{name}' error: {type(e).__name__}: {str(e)[:40]}")

    if stats['expanded'] > 0:
        log.info(f"        ✓ Expanded {stats['expanded']} accordion(s)")
    else:
        log.info(
            f"        → No accordions to expand (found: {stats['found']}, already open: {stats['already_expanded']})")

    return stats


def click_nav_tabs(page: Page) -> dict:
    """Click navigation tabs to load content."""
    log.info("    [TABS] Clicking navigation tabs...")

    stats = {
        'found': 0,
        'clicked': 0,
        'skipped_external': 0,
        'skipped_selected': 0,
        'errors': []
    }

    tab_selectors = [
        ("[role='tab']", "role=tab"),
        (".nav-link[data-toggle='tab']", "nav-link data-toggle"),
        ("[class*='tab-link']", "tab-link class"),
    ]

    for selector, name in tab_selectors:
        try:
            log.debug(f"  Trying tab selector: {name}")
            tabs = page.locator(selector)
            count = tabs.count()

            if count > 0:
                log.debug(f"  Found {count} tabs with selector: {name}")
                stats['found'] += count

            for i in range(count):
                try:
                    tab = tabs.nth(i)
                    if tab.is_visible(timeout=300):
                        href = tab.get_attribute("href") or ""
                        aria_controls = tab.get_attribute("aria-controls")
                        aria_selected = tab.get_attribute("aria-selected")
                        tab_text = (tab.text_content() or "").strip()[:30]

                        log.debug(
                            f"  Tab {i}: '{tab_text}' href={href[:30] if href else 'none'} controls={aria_controls}")

                        # Skip if external link
                        if href and not href.startswith("#") and not aria_controls:
                            if href.startswith("http") or href.startswith("/"):
                                stats['skipped_external'] += 1
                                log.debug(f"  Skipping external tab: {tab_text}")
                                continue

                        # Skip if already selected
                        if aria_selected == "true":
                            stats['skipped_selected'] += 1
                            log.debug(f"  Tab already selected: {tab_text}")
                            continue

                        # Click the tab
                        log.debug(f"  Clicking tab: {tab_text}")
                        tab.click()
                        stats['clicked'] += 1
                        time.sleep(0.4)

                except Exception as e:
                    error_msg = f"Tab {i} error: {type(e).__name__}: {str(e)[:40]}"
                    log.debug(f"  {error_msg}")
                    stats['errors'].append(error_msg)

        except Exception as e:
            log.debug(f"  Selector '{name}' error: {type(e).__name__}: {str(e)[:40]}")

    if stats['clicked'] > 0:
        log.info(f"        ✓ Clicked {stats['clicked']} tab(s)")
    else:
        log.info(
            f"        → No tabs clicked (found: {stats['found']}, external: {stats['skipped_external']}, selected: {stats['skipped_selected']})")

    return stats


def scroll_page(page: Page) -> dict:
    """Scroll through page to trigger lazy loading."""
    log.info("    [SCROLL] Scrolling page for lazy content...")

    stats = {
        'success': True,
        'height': 0,
        'steps': 0,
        'error': None
    }

    try:
        scroll_info = page.evaluate("""async () => {
            const delay = ms => new Promise(r => setTimeout(r, ms));
            const height = document.body.scrollHeight;
            const step = window.innerHeight;
            let scrolls = 0;

            for (let y = 0; y < height; y += step) {
                window.scrollTo(0, y);
                scrolls++;
                await delay(150);
            }
            window.scrollTo(0, 0);

            return { height: height, steps: scrolls, viewportHeight: step };
        }""")

        stats['height'] = scroll_info['height']
        stats['steps'] = scroll_info['steps']
        stats['viewport_height'] = scroll_info['viewportHeight']

        log.info(f"        ✓ Scrolled {scroll_info['steps']} times (page height: {scroll_info['height']:,}px)")
        time.sleep(0.5)

    except Exception as e:
        stats['success'] = False
        stats['error'] = f"{type(e).__name__}: {str(e)}"
        log.error(f"        ✗ Scroll error: {stats['error']}")

    return stats


def capture_page_screenshots(page: Page, output_dir: Path, page_name: str) -> dict:
    """
    Capture screenshots of the entire page by scrolling and stitching.
    Compresses images for LLM-friendly file sizes.
    """
    log.info("    [SCREENSHOTS] Capturing page screenshots...")

    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        'full_page': None,
        'scroll_screenshots': [],
        'total_captured': 0,
        'page_height': 0,
        'viewport_height': 0,
        'errors': []
    }

    # Determine file extension
    ext = ".jpg" if SCREENSHOT_FORMAT == "jpeg" else ".png"

    # Step 1: Aggressive scrolling to load ALL lazy content
    log.info("        → Aggressive scroll to load all lazy content...")
    try:
        scroll_result = page.evaluate("""async () => {
            const delay = ms => new Promise(r => setTimeout(r, ms));

            let maxHeight = 0;
            let stableCount = 0;

            for (let round = 0; round < 5; round++) {
                const step = Math.floor(window.innerHeight / 3);
                let currentY = 0;

                while (currentY < document.body.scrollHeight + window.innerHeight) {
                    window.scrollTo(0, currentY);
                    currentY += step;
                    await delay(100);
                }

                await delay(800);

                const newHeight = Math.max(
                    document.body.scrollHeight,
                    document.documentElement.scrollHeight,
                    document.body.offsetHeight
                );

                if (newHeight === maxHeight) {
                    stableCount++;
                    if (stableCount >= 2) break;
                } else {
                    stableCount = 0;
                    maxHeight = newHeight;
                }
            }

            window.scrollTo(0, 0);
            await delay(500);

            return {
                finalHeight: maxHeight,
                viewportHeight: window.innerHeight,
                viewportWidth: window.innerWidth
            };
        }""")

        stats['page_height'] = scroll_result['finalHeight']
        stats['viewport_height'] = scroll_result['viewportHeight']

        log.info(f"        ✓ Page height after lazy load: {scroll_result['finalHeight']:,}px")

    except Exception as e:
        log.error(f"        ✗ Scroll error: {type(e).__name__}: {str(e)}")
        stats['errors'].append(f"Scroll error: {str(e)}")
        stats['page_height'] = 5000
        stats['viewport_height'] = 1080

    # Step 2: Force load all images
    log.info("        → Force loading all images...")
    try:
        page.evaluate("""() => {
            document.querySelectorAll('img').forEach(img => {
                ['data-src', 'data-lazy-src', 'data-original', 'data-lazy'].forEach(attr => {
                    if (img.getAttribute(attr)) {
                        img.src = img.getAttribute(attr);
                    }
                });
                if (img.loading === 'lazy') img.loading = 'eager';
                if (!img.complete) img.src = img.src;
            });

            document.querySelectorAll('img[data-srcset]').forEach(img => {
                if (img.dataset.srcset) img.srcset = img.dataset.srcset;
            });
        }""")
        time.sleep(1.0)
    except Exception as e:
        log.debug(f"        Image loading warning: {str(e)[:40]}")

    # Step 3: Take scroll screenshots
    log.info("        → Capturing scroll screenshots...")

    viewport_height = stats['viewport_height'] or 1080
    page_height = stats['page_height'] or 5000

    step_size = int(viewport_height * 0.7)
    num_screenshots = max(1, int((page_height / step_size) + 2))
    num_screenshots = min(num_screenshots, 40)

    log.info(f"        → Taking {num_screenshots} screenshots (page: {page_height:,}px, step: {step_size}px)")

    scroll_y = 0
    screenshot_index = 0
    temp_screenshots = []  # Store paths for stitching

    while screenshot_index < num_screenshots:
        try:
            page.evaluate(f"window.scrollTo(0, {scroll_y})")
            time.sleep(0.5)

            actual_scroll = page.evaluate("window.scrollY")

            screenshot_index += 1
            # Take as PNG first (will convert later)
            temp_path = screenshots_dir / f"{page_name}_scroll_{screenshot_index:02d}_temp.png"
            page.screenshot(path=str(temp_path))
            temp_screenshots.append(temp_path)

            log.debug(f"        Screenshot {screenshot_index}: y={actual_scroll}")

            at_bottom = page.evaluate("""() => {
                return (window.scrollY + window.innerHeight) >= (document.body.scrollHeight - 10);
            }""")

            if at_bottom:
                log.debug(f"        Reached bottom at screenshot {screenshot_index}")
                break

            scroll_y += step_size

        except Exception as e:
            error_msg = f"Screenshot {screenshot_index} error: {type(e).__name__}: {str(e)[:40]}"
            log.error(f"        ✗ {error_msg}")
            stats['errors'].append(error_msg)
            break

    log.info(f"        ✓ Captured {len(temp_screenshots)} raw screenshots")

    # Step 4: Process and compress screenshots using PIL
    log.info(f"        → Compressing screenshots (format: {SCREENSHOT_FORMAT}, quality: {SCREENSHOT_QUALITY})...")
    try:
        from PIL import Image

        processed_screenshots = []

        for i, temp_path in enumerate(temp_screenshots):
            if not temp_path.exists():
                continue

            try:
                img = Image.open(temp_path)

                # Convert to RGB if necessary (for JPEG)
                if SCREENSHOT_FORMAT == "jpeg" and img.mode in ('RGBA', 'P'):
                    # Create white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'RGBA':
                        background.paste(img, mask=img.split()[3])
                    else:
                        background.paste(img)
                    img = background

                # Resize if needed
                if SCREENSHOT_MAX_WIDTH and img.width > SCREENSHOT_MAX_WIDTH:
                    ratio = SCREENSHOT_MAX_WIDTH / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((SCREENSHOT_MAX_WIDTH, new_height), Image.LANCZOS)

                # Save compressed
                final_path = screenshots_dir / f"{page_name}_scroll_{i + 1:02d}{ext}"

                if SCREENSHOT_FORMAT == "jpeg":
                    img.save(final_path, 'JPEG', quality=SCREENSHOT_QUALITY, optimize=True)
                else:
                    img.save(final_path, 'PNG', optimize=True)

                file_size = final_path.stat().st_size

                stats['scroll_screenshots'].append({
                    'index': i + 1,
                    'path': f"screenshots/{final_path.name}",
                    'size': file_size,
                    'width': img.width,
                    'height': img.height
                })
                stats['total_captured'] += 1
                processed_screenshots.append((final_path, img.size))

                img.close()

                # Remove temp file
                temp_path.unlink()

            except Exception as e:
                log.debug(f"        Error processing screenshot {i + 1}: {str(e)[:40]}")
                # Keep temp as fallback
                if temp_path.exists():
                    final_path = screenshots_dir / f"{page_name}_scroll_{i + 1:02d}.png"
                    temp_path.rename(final_path)
                    stats['scroll_screenshots'].append({
                        'index': i + 1,
                        'path': f"screenshots/{final_path.name}",
                        'size': final_path.stat().st_size
                    })
                    stats['total_captured'] += 1

        total_scroll_size = sum(s['size'] for s in stats['scroll_screenshots'])
        log.info(
            f"        ✓ Compressed {len(stats['scroll_screenshots'])} screenshots ({total_scroll_size / 1024:.0f} KB total)")

        # Step 5: Create stitched full-page image
        log.info("        → Creating stitched full-page screenshot...")

        if len(stats['scroll_screenshots']) > 0:
            images = []
            for ss in stats['scroll_screenshots']:
                img_path = output_dir / ss['path']
                if img_path.exists():
                    images.append(Image.open(img_path))

            if images:
                width = images[0].width
                single_height = images[0].height

                overlap = int(single_height * 0.3)
                total_height = single_height + (len(images) - 1) * (single_height - overlap)

                # Cap the height
                if SCREENSHOT_FULL_PAGE_MAX_HEIGHT:
                    total_height = min(total_height, SCREENSHOT_FULL_PAGE_MAX_HEIGHT)

                # Create stitched image
                if SCREENSHOT_FORMAT == "jpeg":
                    stitched = Image.new('RGB', (width, total_height), (255, 255, 255))
                else:
                    stitched = Image.new('RGBA', (width, total_height), (255, 255, 255, 255))

                y_offset = 0
                for i, img in enumerate(images):
                    # Convert if needed
                    if SCREENSHOT_FORMAT == "jpeg" and img.mode != 'RGB':
                        img = img.convert('RGB')

                    # Check if we'd exceed max height
                    if y_offset + img.height > total_height:
                        # Crop the image to fit
                        crop_height = total_height - y_offset
                        if crop_height > 0:
                            img = img.crop((0, 0, img.width, crop_height))
                            stitched.paste(img, (0, y_offset))
                        break

                    stitched.paste(img, (0, y_offset))

                    if i < len(images) - 1:
                        y_offset += single_height - overlap

                # Crop to actual content
                final_height = min(total_height, y_offset + single_height)
                stitched = stitched.crop((0, 0, width, final_height))

                # Save compressed
                full_page_path = screenshots_dir / f"{page_name}_full_page{ext}"

                if SCREENSHOT_FORMAT == "jpeg":
                    stitched.save(full_page_path, 'JPEG', quality=SCREENSHOT_QUALITY, optimize=True)
                else:
                    stitched.save(full_page_path, 'PNG', optimize=True)

                file_size = full_page_path.stat().st_size
                stats['full_page'] = {
                    'path': f"screenshots/{full_page_path.name}",
                    'size': file_size,
                    'width': stitched.width,
                    'height': stitched.height,
                    'method': 'stitched'
                }
                stats['total_captured'] += 1

                log.info(
                    f"        ✓ Full page: {full_page_path.name} ({stitched.width}x{stitched.height}, {file_size / 1024:.0f} KB)")

                # Close images
                for img in images:
                    img.close()
                stitched.close()

    except ImportError:
        log.warning("        ⚠ PIL not installed - screenshots not compressed")
        # Rename temp files
        for i, temp_path in enumerate(temp_screenshots):
            if temp_path.exists():
                final_path = screenshots_dir / f"{page_name}_scroll_{i + 1:02d}.png"
                temp_path.rename(final_path)
                stats['scroll_screenshots'].append({
                    'index': i + 1,
                    'path': f"screenshots/{final_path.name}",
                    'size': final_path.stat().st_size
                })
                stats['total_captured'] += 1

        # Fallback full page
        try:
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.3)
            full_page_path = screenshots_dir / f"{page_name}_full_page.png"
            page.screenshot(path=str(full_page_path), full_page=True, timeout=60000)
            file_size = full_page_path.stat().st_size
            stats['full_page'] = {
                'path': f"screenshots/{full_page_path.name}",
                'size': file_size,
                'method': 'playwright'
            }
            stats['total_captured'] += 1
        except Exception as e:
            log.error(f"        ✗ Full page failed: {str(e)[:50]}")

    except Exception as e:
        error_msg = f"Processing error: {type(e).__name__}: {str(e)}"
        log.error(f"        ✗ {error_msg}")
        stats['errors'].append(error_msg)

        # Clean up temp files
        for temp_path in temp_screenshots:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except:
                    pass

    # Scroll back to top
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except:
        pass

    # Calculate total size
    total_size = sum(s.get('size', 0) for s in stats['scroll_screenshots'])
    if stats['full_page']:
        total_size += stats['full_page'].get('size', 0)

    log.info(f"        ✓ Total: {stats['total_captured']} screenshots ({total_size / 1024:.0f} KB)")

    return stats


def make_all_visible(page: Page) -> dict:
    """Make all tab panels and accordion content visible."""
    log.info("    [VISIBILITY] Making all panels visible...")

    try:
        stats = page.evaluate("""() => {
            let stats = { tabPanels: 0, accordions: 0, lazyImages: 0 };

            // Tab panels
            document.querySelectorAll('[role="tabpanel"]').forEach(panel => {
                panel.style.display = 'block';
                panel.style.visibility = 'visible';
                panel.style.opacity = '1';
                panel.style.height = 'auto';
                panel.removeAttribute('hidden');
                stats.tabPanels++;
            });

            // Accordions
            document.querySelectorAll('.collapse, .accordion-collapse, .js-accordion__panel').forEach(panel => {
                panel.classList.add('show');
                panel.style.display = 'block';
                panel.style.height = 'auto';
                panel.removeAttribute('aria-hidden');
                stats.accordions++;
            });

            // Lazy images
            document.querySelectorAll('img[data-src]').forEach(img => {
                if (img.dataset.src) {
                    img.src = img.dataset.src;
                    stats.lazyImages++;
                }
            });
            document.querySelectorAll('img[loading="lazy"]').forEach(img => {
                img.loading = 'eager';
                stats.lazyImages++;
            });

            return stats;
        }""")

        log.info(
            f"        ✓ Made visible: {stats['tabPanels']} tab panels, {stats['accordions']} accordions, {stats['lazyImages']} lazy images")
        return stats

    except Exception as e:
        log.error(f"        ✗ Visibility error: {type(e).__name__}: {str(e)}")
        return {'tabPanels': 0, 'accordions': 0, 'lazyImages': 0}


def get_full_html(page: Page) -> tuple:
    """Get complete HTML. Returns (html, error)."""
    log.debug("Getting full HTML content...")

    try:
        html = page.evaluate("() => '<!DOCTYPE html>' + document.documentElement.outerHTML")
        log.debug(f"Got HTML via outerHTML: {len(html):,} bytes")
        return html, None
    except Exception as e:
        log.warning(f"outerHTML failed: {str(e)[:40]}, trying page.content()")
        try:
            html = page.content()
            log.debug(f"Got HTML via content(): {len(html):,} bytes")
            return html, None
        except Exception as e2:
            error_msg = f"Failed to get HTML: {type(e2).__name__}: {str(e2)}"
            log.error(error_msg)
            return "", error_msg


def extract_images_and_links(page: Page, base_url: str) -> tuple:
    """Extract all images and links. Returns (data, error)."""
    log.info("    [EXTRACT] Extracting images and links...")

    try:
        data = page.evaluate("""(baseUrl) => {
            const result = { images: [], links: [], hrefs: [] };
            const seenImages = new Set();
            const seenLinks = new Set();

            // Images
            document.querySelectorAll('img').forEach((img, idx) => {
                const src = img.src || img.dataset.src || img.dataset.lazySrc || '';
                if (src && !seenImages.has(src) && !src.startsWith('data:')) {
                    seenImages.add(src);
                    result.images.push({
                        index: idx,
                        src: src,
                        alt: img.alt || '',
                        title: img.title || '',
                        width: img.naturalWidth || img.width || null,
                        height: img.naturalHeight || img.height || null
                    });
                }
            });

            // Background images
            document.querySelectorAll('*').forEach(el => {
                try {
                    const style = window.getComputedStyle(el);
                    const bg = style.backgroundImage;
                    if (bg && bg !== 'none' && bg.includes('url(')) {
                        const match = bg.match(/url\\(['"']?([^'"')]+)['"']?\\)/);
                        if (match && match[1] && !seenImages.has(match[1]) && !match[1].startsWith('data:')) {
                            seenImages.add(match[1]);
                            result.images.push({
                                index: result.images.length,
                                src: match[1],
                                type: 'background-image'
                            });
                        }
                    }
                } catch(e) {}
            });

            // Links
            document.querySelectorAll('a[href]').forEach((a, idx) => {
                const href = a.href || '';
                const text = (a.innerText || '').trim();
                if (href && !seenLinks.has(href)) {
                    seenLinks.add(href);
                    result.links.push({
                        index: idx,
                        href: href,
                        text: text.substring(0, 200),
                        title: a.title || '',
                        isExternal: !href.includes(window.location.hostname),
                        isAnchor: href.startsWith('#')
                    });
                    result.hrefs.push({
                        href: href,
                        text: text.substring(0, 100)
                    });
                }
            });

            return result;
        }""", base_url)

        log.info(f"        ✓ Found {len(data['images'])} images, {len(data['links'])} links")
        return data, None

    except Exception as e:
        error_msg = f"Extract error: {type(e).__name__}: {str(e)}"
        log.error(f"        ✗ {error_msg}")
        return {'images': [], 'links': [], 'hrefs': []}, error_msg


def download_images(images: list, output_dir: Path, base_url: str) -> tuple:
    """Download all images. Returns (downloaded_list, stats)."""
    log.info(f"    [DOWNLOAD] Downloading {len(images)} images...")

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        'total': len(images),
        'success': 0,
        'failed': 0,
        'skipped': 0,
        'errors': []
    }

    downloaded = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    for img in images:
        src = img.get('src', '')
        if not src:
            stats['skipped'] += 1
            continue

        try:
            # Handle relative URLs
            original_src = src
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                parsed = urlparse(base_url)
                src = f"{parsed.scheme}://{parsed.netloc}{src}"
            elif not src.startswith('http'):
                src = urljoin(base_url, src)

            # Generate filename
            url_hash = hashlib.md5(src.encode()).hexdigest()[:10]
            ext = Path(urlparse(src).path).suffix.lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.bmp']:
                ext = '.jpg'

            filename = f"img_{img['index']:03d}_{url_hash}{ext}"
            filepath = images_dir / filename

            log.debug(f"  Downloading: {src[:60]}...")

            # Download
            response = requests.get(src, headers=headers, timeout=IMAGE_DOWNLOAD_TIMEOUT, stream=True)
            response.raise_for_status()

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            file_size = filepath.stat().st_size
            img['local_path'] = f"images/{filename}"
            img['download_status'] = 'success'
            img['file_size'] = file_size
            stats['success'] += 1

            log.debug(f"  ✓ Downloaded: {filename} ({file_size:,} bytes)")

        except requests.exceptions.Timeout:
            error_msg = f"Timeout downloading: {src[:50]}"
            log.debug(f"  ✗ {error_msg}")
            img['local_path'] = None
            img['download_status'] = 'failed: timeout'
            stats['failed'] += 1
            stats['errors'].append(error_msg)

        except requests.exceptions.RequestException as e:
            error_msg = f"Request error for {src[:40]}: {str(e)[:30]}"
            log.debug(f"  ✗ {error_msg}")
            img['local_path'] = None
            img['download_status'] = f'failed: {str(e)[:40]}'
            stats['failed'] += 1
            stats['errors'].append(error_msg)

        except Exception as e:
            error_msg = f"Error downloading {src[:40]}: {type(e).__name__}: {str(e)[:30]}"
            log.debug(f"  ✗ {error_msg}")
            img['local_path'] = None
            img['download_status'] = f'failed: {type(e).__name__}'
            stats['failed'] += 1
            stats['errors'].append(error_msg)

        downloaded.append(img)

    log.info(
        f"        ✓ Downloaded: {stats['success']}/{stats['total']} (failed: {stats['failed']}, skipped: {stats['skipped']})")

    return downloaded, stats


def scrape_single_url(page: Page, url: str, data_segment: str, base_dir: Path) -> dict:
    """Scrape a single URL with full logging."""

    page_name = get_page_name_from_url(url)
    output_dir = create_output_folder(data_segment, url, base_dir)

    log.info(f"\n{'─' * 60}")
    log.info(f"SCRAPING: {url}")
    log.info(f"Segment: {data_segment} | Page: {page_name}")
    log.info(f"Output: {output_dir.relative_to(base_dir)}")
    log.info(f"{'─' * 60}")

    result = {
        'url': url,
        'data_segment': data_segment,
        'page_name': page_name,
        'output_folder': str(output_dir.relative_to(base_dir)),
        'timestamp': datetime.now().isoformat(),
        'success': False,
        'stages': {},
        'stats': {
            'popups_dismissed': 0,
            'accordions_expanded': 0,
            'tabs_clicked': 0,
            'screenshots_captured': 0,
            'images_found': 0,
            'images_downloaded': 0,
            'links_found': 0,
            'dom_size': 0,
        },
        'files': {},
        'errors': []
    }

    try:
        # Stage 1: Navigate
        log.info("\n[1/8] NAVIGATING to URL...")
        start_time = time.time()

        try:
            page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
            nav_time = time.time() - start_time
            log.info(f"        ✓ Page loaded in {nav_time:.1f}s")
            result['stages']['navigate'] = {'success': True, 'time': nav_time}
        except PlaywrightError as e:
            error_msg = f"Navigation failed: {type(e).__name__}: {str(e)}"
            log.error(f"        ✗ {error_msg}")
            result['stages']['navigate'] = {'success': False, 'error': error_msg}
            result['errors'].append(error_msg)
            raise

        time.sleep(WAIT_AFTER_LOAD)

        # Stage 2: Wait for content
        log.info("\n[2/8] WAITING for page content...")

        if not wait_for_page_content(page, timeout=15):
            error_msg = "Page content never loaded (body too small)"
            log.error(f"        ✗ {error_msg}")
            result['stages']['wait_content'] = {'success': False, 'error': error_msg}
            result['errors'].append(error_msg)
            raise Exception(error_msg)

        has_body, body_size = verify_page_has_body(page)
        log.info(f"        ✓ Page content ready ({body_size:,} bytes)")
        result['stages']['wait_content'] = {'success': True, 'body_size': body_size}

        # Stage 3: Handle popups
        log.info("\n[3/8] HANDLING popups...")
        popup_stats = handle_all_popups(page, output_dir)
        result['stages']['popups'] = popup_stats
        result['stats']['popups_dismissed'] = popup_stats['total_handled']
        result['errors'].extend(popup_stats['errors'])

        # Verify content after popups
        has_body, body_size = verify_page_has_body(page)
        if not has_body:
            error_msg = f"Content lost after popup handling (body: {body_size} bytes)"
            log.error(f"        ✗ {error_msg}")
            result['errors'].append(error_msg)
            raise Exception(error_msg)
        log.info(f"        ✓ Content verified ({body_size:,} bytes)")

        # Stage 4: Scroll
        log.info("\n[4/9] SCROLLING page...")
        scroll_stats = scroll_page(page)
        result['stages']['scroll'] = scroll_stats

        # Stage 5: Tabs
        log.info("\n[5/9] CLICKING tabs...")
        tab_stats = click_nav_tabs(page)
        result['stages']['tabs'] = tab_stats
        result['stats']['tabs_clicked'] = tab_stats['clicked']
        result['errors'].extend(tab_stats['errors'])

        # Stage 6: Accordions
        log.info("\n[6/9] EXPANDING accordions...")
        accordion_stats = expand_accordions(page)
        result['stages']['accordions'] = accordion_stats
        result['stats']['accordions_expanded'] = accordion_stats['expanded']
        result['errors'].extend(accordion_stats['errors'])

        # Make all visible
        log.info("\n[6b/8] MAKING all content visible...")
        visibility_stats = make_all_visible(page)
        result['stages']['visibility'] = visibility_stats
        time.sleep(0.5)

        # Stage 7: Screenshots (NEW)
        log.info("\n[7/9] CAPTURING screenshots...")
        screenshot_stats = capture_page_screenshots(page, output_dir, page_name)
        result['stages']['screenshots'] = screenshot_stats
        result['stats']['screenshots_captured'] = screenshot_stats['total_captured']
        result['errors'].extend(screenshot_stats['errors'][:3])  # Limit errors

        if screenshot_stats['full_page']:
            result['files']['screenshot_full'] = screenshot_stats['full_page']['path']
        if screenshot_stats['scroll_screenshots']:
            result['files']['screenshots_scroll'] = [s['path'] for s in screenshot_stats['scroll_screenshots']]

        # Final debug screenshot (only if DEBUG_SCREENSHOTS enabled)
        if DEBUG_SCREENSHOTS:
            try:
                page.screenshot(path=str(output_dir / "debug_3_final.png"), full_page=True)
                log.debug("Saved final debug screenshot")
            except Exception as e:
                log.debug(f"Could not save final screenshot: {str(e)[:40]}")

        # Stage 8: Extract
        log.info("\n[8/9] EXTRACTING data...")
        extracted, extract_error = extract_images_and_links(page, url)
        result['stats']['images_found'] = len(extracted['images'])
        result['stats']['links_found'] = len(extracted['links'])
        if extract_error:
            result['errors'].append(extract_error)
        result['stages']['extract'] = {
            'success': extract_error is None,
            'images': len(extracted['images']),
            'links': len(extracted['links'])
        }

        # Stage 9: Save
        log.info("\n[9/9] SAVING files...")

        # Save DOM
        html, html_error = get_full_html(page)
        if html_error:
            result['errors'].append(html_error)

        result['stats']['dom_size'] = len(html)

        if len(html) < 5000:
            log.warning(f"        ⚠ DOM seems small: {len(html):,} bytes")

        dom_path = output_dir / f"{page_name}_dom.html"
        with open(dom_path, 'w', encoding='utf-8') as f:
            f.write(html)
        result['files']['dom'] = f"{page_name}_dom.html"
        log.info(f"        ✓ Saved DOM: {dom_path.name} ({len(html):,} bytes)")

        # Download images
        if extracted['images']:
            downloaded, download_stats = download_images(extracted['images'], output_dir, url)
            result['stats']['images_downloaded'] = download_stats['success']
            result['stages']['download'] = download_stats
            result['errors'].extend(download_stats['errors'][:5])  # Limit errors
            extracted['images'] = downloaded

        # Save mapping JSON
        mapping = {
            'url': url,
            'data_segment': data_segment,
            'page_title': page.title(),
            'scraped_at': result['timestamp'],
            'images': extracted['images'],
            'links': extracted['links'],
            'hrefs': extracted['hrefs'],
            'statistics': result['stats']
        }

        json_path = output_dir / f"{page_name}_mapping.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
        result['files']['mapping'] = f"{page_name}_mapping.json"
        log.info(f"        ✓ Saved mapping: {json_path.name}")

        result['success'] = True
        log.info(f"\n{'─' * 60}")
        log.info(f"✓ COMPLETED: {page_name}")
        log.info(
            f"  DOM: {result['stats']['dom_size']:,}b | Screenshots: {result['stats']['screenshots_captured']} | Images: {result['stats']['images_downloaded']}/{result['stats']['images_found']} | Links: {result['stats']['links_found']}")
        log.info(f"{'─' * 60}")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        log.error(f"\n✗ FAILED: {error_msg}")
        log.debug(f"Traceback:\n{traceback.format_exc()}")

        if error_msg not in result['errors']:
            result['errors'].append(error_msg)

        # Emergency save
        try:
            emergency_html, _ = get_full_html(page)
            if emergency_html:
                emergency_path = output_dir / f"{page_name}_emergency.html"
                with open(emergency_path, 'w', encoding='utf-8') as f:
                    f.write(emergency_html)
                result['files']['emergency'] = f"{page_name}_emergency.html"
                log.info(f"        Saved emergency HTML: {emergency_path.name}")
        except Exception as e2:
            log.debug(f"Could not save emergency HTML: {str(e2)[:40]}")

    return result


def main():
    global log

    # Get Excel file
    excel_file = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXCEL
    excel_path = Path(excel_file)

    if not excel_path.exists():
        print(f"✗ Excel file not found: {excel_file}")
        return 1

    # Setup logging
    OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    log = setup_logging(OUTPUT_BASE)

    # Load URLs
    log.info(f"\n{'#' * 60}")
    log.info("ADP BATCH PAGE SCRAPER v4 - With Detailed Logging")
    log.info(f"{'#' * 60}")
    log.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Excel file: {excel_path.absolute()}")
    log.info(f"Output dir: {OUTPUT_BASE}")

    try:
        df = pd.read_excel(excel_path)
        log.info(f"Loaded {len(df)} rows from Excel")
        log.info(f"Columns: {df.columns.tolist()}")
    except Exception as e:
        log.error(f"Failed to read Excel: {type(e).__name__}: {str(e)}")
        return 1

    # Find columns
    segment_col = None
    url_col = None

    for col in df.columns:
        col_lower = col.lower()
        if 'segment' in col_lower:
            segment_col = col
        if 'source' in col_lower or 'url' in col_lower:
            url_col = col

    if not segment_col:
        segment_col = df.columns[0]
    if not url_col:
        url_col = df.columns[1]

    log.info(f"Using columns: Segment='{segment_col}', URL='{url_col}'")
    log.info(f"\n{'=' * 60}")

    # Process URLs
    results = []
    total = len(df)
    successful = 0
    failed = 0

    with sync_playwright() as p:
        log.info("Launching browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        log.info("Browser ready")

        for idx, row in df.iterrows():
            url = str(row[url_col]).strip()
            data_segment = str(row[segment_col]).strip()

            if not url or url == 'nan' or not url.startswith('http'):
                log.warning(f"\n[{idx + 1}/{total}] Skipping invalid URL: {url}")
                continue

            log.info(f"\n{'=' * 60}")
            log.info(f"[{idx + 1}/{total}] Processing...")
            log.info(f"{'=' * 60}")

            # Retry logic
            for attempt in range(MAX_RETRIES):
                if attempt > 0:
                    log.info(f"\n--- RETRY {attempt + 1}/{MAX_RETRIES} ---")
                    time.sleep(2)

                result = scrape_single_url(page, url, data_segment, OUTPUT_BASE)

                if result['success']:
                    successful += 1
                    break
                else:
                    if attempt == MAX_RETRIES - 1:
                        failed += 1
                        log.error(f"All {MAX_RETRIES} attempts failed for: {url}")

            results.append(result)

            # Progress
            log.info(f"\n>>> Progress: {idx + 1}/{total} | Success: {successful} | Failed: {failed}")

        browser.close()
        log.info("\nBrowser closed")

    # Save batch report
    report = {
        'excel_file': str(excel_path.absolute()),
        'timestamp': datetime.now().isoformat(),
        'total_urls': total,
        'successful': successful,
        'failed': failed,
        'results': results
    }

    report_path = OUTPUT_BASE / "batch_report.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Summary
    log.info(f"\n{'#' * 60}")
    log.info("BATCH COMPLETE")
    log.info(f"{'#' * 60}")
    log.info(f"  Total URLs:  {total}")
    log.info(f"  Successful:  {successful}")
    log.info(f"  Failed:      {failed}")
    log.info(f"  Success Rate: {successful / total * 100:.1f}%" if total > 0 else "N/A")
    log.info(f"  Output dir:  {OUTPUT_BASE}")
    log.info(f"  Report:      {report_path}")
    log.info(f"  Log file:    {OUTPUT_BASE / 'scraper.log'}")

    # List failures
    failed_results = [r for r in results if not r['success']]
    if failed_results:
        log.info(f"\nFailed URLs ({len(failed_results)}):")
        for r in failed_results:
            log.info(f"  • {r['url'][:60]}...")
            for err in r['errors'][:2]:
                log.info(f"    Error: {err[:70]}")

    log.info(f"\nFinished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())