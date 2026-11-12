"""Resolve public announcement titles whose SPA click handlers omit hrefs."""
import time
import re
from selenium.common.exceptions import StaleElementReferenceException
from html import escape
from urllib.parse import urlsplit
from .listing import parse_links, page_problem

# Only observed announcement-title controls; never click registration, quotation
# or purchase buttons. Record the actual navigation URL rather than inventing IDs.
TITLE_SELECTORS = {
    'ec.minmetals.com.cn': ('a[href="javascript:;"]', '【'),
    'sgccetp.com.cn': ('span.pad', ''),
    'srm.longi.com': ('.title.item', ''),
    'xdsc.xcmg.com': ('li.pt5.pb5', ''),
    'zbcg.jchc.cn': ('div[style*="text-overflow: ellipsis"]', ''),
    'hgcg.hghngroup.com': ('.announce-title span', ''),
    'ebid.espic.com.cn': ('a:has(.z-tender-title)', ''),
    'c.cnbm.com.cn': ('p.title_left span[style]', '['),
    'nsrm.dongfang.com': ('.title-text span', ''),
    'scm.powerchina.cn': ('.field-item .item-con[onclick]', ''),
    'zjzcw.iccec.cn': ('.itemBox .workDynamics-item-title span.ellipsis[title]', ''),
}


def resolve_titles(driver, url, source, stop_event=None, limit=80):
    profile = TITLE_SELECTORS.get(urlsplit(url).hostname)
    if not profile:
        return [], 0
    selector, prefix = profile
    include_hidden = urlsplit(url).hostname == 'nsrm.dongfang.com'
    read_title = lambda element: (element.get_attribute('textContent') if include_hidden else element.text).strip()
    candidates = []
    restricted = 0
    for element in driver.find_elements('css selector', selector):
        text = read_title(element)
        if urlsplit(url).hostname == 'scm.powerchina.cn':
            args = re.findall(r"'([^']*)'", element.get_attribute('onclick') or '')
            # The public site's own handler requires login for clarifications
            # and invitation notices. Do not trigger its login alert.
            if len(args) == 4 and (args[3] == '6' or (args[3] == '2' and args[2] == '邀请')):
                restricted += 1
                continue
        if 10 <= len(text) <= 200 and (not prefix or text.startswith(prefix)) and (urlsplit(url).hostname == 'zjzcw.iccec.cn' or any(k in text for k in ['采购', '招标', '公告', '中标', '成交', '招募', '询价'])):
            if text not in candidates:
                candidates.append(text)
    main = driver.current_window_handle
    bids, seen, unresolved = [], set(), restricted + max(0, len(candidates)-limit)
    started = time.monotonic()
    consecutive_failures = 0
    for index, text in enumerate(candidates[:limit]):
        if stop_event and stop_event.is_set():
            break
        if time.monotonic() - started > (150 if include_hidden else 45) or consecutive_failures >= 3:
            unresolved += len(candidates[:limit]) - index
            break
        before_count = len(bids)
        original_handles = set(driver.window_handles)
        original_url = driver.current_url
        try:
            # SPA back-navigation may briefly expose the old component before
            # replacing it. Reacquire the observed title instead of losing it to
            # a stale element reference during that render transition.
            for render_attempt in range(3):
                try:
                    element = next((e for e in driver.find_elements('css selector', selector) if read_title(e) == text), None)
                    if element is None:
                        time.sleep(0.3)
                        continue
                    context = element.find_element('xpath', '..').text
                    full_title = element.get_attribute('title') or text
                    if urlsplit(url).hostname == 'zjzcw.iccec.cn':
                        card = element.find_element('xpath', 'ancestor::*[contains(@class,"itemBox")][1]')
                        context = card.text
                        heading = element.find_element('xpath', 'ancestor::*[contains(@class,"workDynamics-item-title")][1]')
                        category = heading.find_element('css selector', '.iconTitle').text
                        full_title = '[' + category + ']' + full_title
                    if urlsplit(url).hostname == 'srm.longi.com':
                        # Recruitment cards bind navigation to the details button,
                        # not to the text heading.
                        element.find_element('xpath', '..').find_element('css selector', 'button').click()
                    elif include_hidden and not element.is_displayed():
                        # Public announcement data is preloaded for other tabs.
                        # Invoke only the same read-only detail-title handler.
                        driver.execute_script('arguments[0].click()', element)
                    else:
                        element.click()
                    break
                except StaleElementReferenceException:
                    if render_attempt == 2:
                        raise
                    time.sleep(0.3)
            else:
                unresolved += 1
                continue
            deadline = time.monotonic() + 3
            child = None
            while time.monotonic() < deadline:
                new_handles = set(driver.window_handles) - original_handles
                if new_handles:
                    child = next(iter(new_handles))
                    driver.switch_to.window(child)
                if driver.current_url not in (original_url, 'about:blank'):
                    break
                if stop_event and stop_event.wait(0.2):
                    break
                if not stop_event:
                    time.sleep(0.2)
            actual_url = driver.current_url
            # A new tab can expose its URL before its body is rendered. Treating
            # that transient empty body as a failed page intermittently dropped
            # valid announcements (observed on Huaguang's public portal).
            rendered_deadline = time.monotonic() + 5
            while actual_url != original_url and time.monotonic() < rendered_deadline:
                ready = driver.execute_script('return document.readyState !== "loading" && document.body && document.body.innerText.trim().length > 0')
                if ready:
                    break
                if stop_event and stop_event.wait(0.2):
                    break
                if not stop_event:
                    time.sleep(0.2)
                actual_url = driver.current_url
            if actual_url == original_url or urlsplit(actual_url).scheme not in ('http', 'https') or page_problem(driver.page_source, actual_url):
                unresolved += 1
            elif actual_url not in seen:
                seen.add(actual_url)
                # Reuse date normalization, preserving the title actually clicked.
                markup = '<li><a href="' + escape(actual_url, quote=True) + '">' + escape(full_title) + '</a> ' + escape(context) + '</li>'
                bids.extend(parse_links(markup, actual_url, source))
        except Exception:
            unresolved += 1
        finally:
            for handle in set(driver.window_handles) - original_handles:
                driver.switch_to.window(handle)
                driver.close()
            driver.switch_to.window(main)
            if driver.current_url != original_url:
                driver.back()
                # Allow SPA handlers to restore the list before the next click.
                for _ in range(15):
                    if driver.current_url == original_url and driver.find_elements('css selector', selector):
                        break
                    time.sleep(0.2)
        consecutive_failures = consecutive_failures + 1 if len(bids) == before_count else 0
    return bids, unresolved
