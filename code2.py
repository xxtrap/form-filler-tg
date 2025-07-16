import asyncio
import random
import re
import logging
import sys
import time
import os
import json
from urllib.parse import urljoin, urlparse
from io import BytesIO
from PIL import Image
import requests

# Check for required modules
try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    print("Error: 'playwright' module not found. Install it with: pip install playwright")
    sys.exit(1)

try:
    from duckduckgo_search import DDGS
except ImportError:
    print("Error: 'duckduckgo_search' module not found. Install it with: pip install duckduckgo-search")
    sys.exit(1)

try:
    import dns.resolver
except ImportError:
    print("Error: 'dnspython' module not found. Install it with: pip install dnspython")
    sys.exit(1)

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Warning: 'undetected_chromedriver' not found. Falling back to Playwright-only mode.")
    uc = None

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "7619040891:AAF9pfQQme32XvhTfUb97jzky5w4ZEaBzwc")
CHAT_ID = os.getenv("CHAT_ID", "5172045930")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
KEYWORDS_FILE = "keywords.txt"
SUBMISSION_LOG = "submissions.json"

NAME = os.getenv("NAME", "Kevin Fang")
EMAIL = os.getenv("EMAIL", "kevandcoceo@hotmail.com")
PHONE = os.getenv("PHONE", "+365433225")
ADDRESS = os.getenv("ADDRESS", "123 Main St, New York, NY 10001")
SUBJECT = os.getenv("SUBJECT", "Partnership with Concierge")
MESSAGE = os.getenv("MESSAGE", "Hi I'm Kevin, I run a concierge service and I get a few issues with one of my clients, a politician and ive been subpeoned i need someone to represewnt me i have done nothing wrong kindly reach oput via email as im not in the states currently ")

# Load keywords
if os.path.exists(KEYWORDS_FILE):
    with open(KEYWORDS_FILE, "r") as f:
        KEYWORDS = [line.strip() for line in f if line.strip()]
else:
    KEYWORDS = [
        "lawyers in California",
        "lawq USA contact",
        "luxury lawyers enquiry",
        "lawyers Europe contact"
    ]

CONTACT_KEYWORDS = ["contact", "enquiry", "connect", "getintouch", "message", "reach", "touch"]
COOKIE_SELECTORS = [
    "#cookie-consent", ".cookie-banner", "#cookie-notice", "#cookiePolicy",
    "#acceptCookies", ".btn-cookies", ".cookie-accept", ".cookie-ok", "#gdpr-consent",
    ".cookie-agree", "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    ".cc-btn", ".cookie-notice-actions button", "button:has-text('Accept')",
    "button:has-text('Agree')", "button:has-text('Allow')", "button:has-text('OK')",
    "button:has-text('I accept')", "button:has-text('I agree')", "button:has-text('Consent')",
    "button:has-text('Got it')", "button:has-text('Close')", "button:has-text('Continue')",
    "button:has-text('Dismiss')", "button:has-text('Yes')", "button:has-text('Accept All')",
    "button:has-text('Allow All')", "button:has-text('I Understand')", "#cookie-accept",
    ".cookie-button", ".cookie-allow", "#acceptCookie", ".btn-cookie", "#cookieAgree",
    "#cookie-ok", "#gdpr-accept", ".js-cookie-accept", ".cookie-close"
]
TERMS_KEYWORDS = ["terms", "conditions", "privacy", "policy", "agree", "accept", "gdpr", "consent"]
POPUP_SELECTORS = [
    ".modal", ".popup", ".dialog", ".lightbox", "#modal", "#popup",
    "div[role='dialog']", "div[class*='modal']", "div[class*='popup']",
    ".overlay", ".notice", ".alert", ".notification", ".interstitial",
    ".slide-in", ".banner", ".ad-container", ".newsletter-popup"
]
CONTACT_NAV_PATTERNS = [
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'contact')]",
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'enquiry')]",
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'connect')]",
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'message')]",
    "//a[contains(@href, 'contact')]",
    "//a[contains(@href, 'enquiry')]",
    "//a[contains(@href, 'connect')]",
    "//a[contains(@id, 'contact')]",
    "//a[contains(@class, 'contact')]",
    "//a[contains(@title, 'Contact')]",
    "//button[contains(., 'Contact')]",
    "//button[contains(., 'Enquire')]"
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("mainguy")

visited_domains = set()

def log_submission(url, status, data=None):
    with open(SUBMISSION_LOG, "a") as f:
        json.dump({"url": url, "status": status, "data": data or {}, "timestamp": time.time()}, f)
        f.write("\n")

def get_mx_records(domain):
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return [str(r.exchange) for r in answers]
    except Exception as e:
        logger.error(f"MX lookup failed for {domain}: {e}")
        return []

def extract_emails(page_source):
    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    return list(set(re.findall(email_pattern, page_source)))

def extract_company_and_city(page, page_source):
    company = "Unknown"
    city = "Unknown"
    try:
        title = page.title() if hasattr(page, 'title') else page_source
        if title:
            company = title.split("|")[0].strip()
        if hasattr(page, 'query_selector'):
            meta_city = page.query_selector("meta[name*='city'], meta[content*='city']")
            if meta_city:
                city = meta_city.get_attribute("content") or "Unknown"
    except:
        pass
    return company, city

def send_to_telegram(image_bytes, caption):
    try:
        if not image_bytes or len(image_bytes) < 1024:
            logger.error("Invalid image for Telegram")
            return
        img = Image.open(BytesIO(image_bytes))
        img = img.resize((1280, 720), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        files = {"photo": ("screenshot.jpg", buf.getvalue())}
        data = {"chat_id": CHAT_ID, "caption": caption[:1024]}
        with requests.Session() as session:
            r = session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data=data,
                files=files,
                timeout=15
            )
            if r.status_code == 200:
                logger.info("Telegram: Message sent successfully")
            else:
                logger.error(f"Telegram error: {r.status_code} - {r.text}")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

async def handle_popups(page):
    for selector in POPUP_SELECTORS:
        try:
            popup = await page.query_selector(selector)
            if popup:
                close_btn = await popup.query_selector(
                    ".close, .dismiss, [aria-label='Close'], [aria-label='Dismiss'], "
                    "[title='Close'], [title='Dismiss'], .btn-close, .popup-close, "
                    ".modal-close, .close-button, .close-icon"
                )
                if not close_btn:
                    close_btn = await popup.query_selector(
                        "button:has-text('Close'), button:has-text('Dismiss'), "
                        "button:has-text('No thanks'), button:has-text('Maybe later'), "
                        "button:has-text('Not now'), button:has-text('Decline')"
                    )
                if close_btn:
                    await close_btn.scroll_into_view_if_needed()
                    await close_btn.click()
                    logger.info(f"✅ Closed popup with selector: {selector}")
                    await asyncio.sleep(1)
                    return True
        except Exception as e:
            logger.debug(f"Popup close failed: {str(e)}")
    return False

async def handle_cookie_consent(page):
    for attempt in range(3):
        for sel in COOKIE_SELECTORS:
            try:
                btn = await page.query_selector(f"{sel}:visible") or await page.query_selector(sel)
                if btn:
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    logger.info(f"✅ Clicked cookie button using selector: {sel}")
                    await asyncio.sleep(1)
                    return True
            except Exception as e:
                logger.debug(f"Cookie click failed on {sel}: {str(e)}")
        await asyncio.sleep(1)
    return False

def start_undetected_driver():
    if not uc:
        logger.warning("undetected_chromedriver not available, skipping")
        return None
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1200,800")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.60 Safari/537.36")
    options.headless = not DEBUG
    try:
        driver = uc.Chrome(options=options, version_main=129)
        return driver
    except Exception as e:
        logger.error(f"Failed to start undetected_chromedriver: {e}")
        return None

async def find_contact_pages_selenium(driver, base_url):
    if not driver:
        return []
    try:
        wait = WebDriverWait(driver, 15)
        driver.get(base_url)
        for selector in POPUP_SELECTORS:
            try:
                popup = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                close_btn = popup.find_element(By.CSS_SELECTOR, ".close, .dismiss, [aria-label='Close'], [aria-label='Dismiss']")
                if close_btn:
                    close_btn.click()
                    logger.info(f"✅ Closed popup with selector: {selector}")
                    time.sleep(1)
                    break
            except:
                continue
        for selector in COOKIE_SELECTORS:
            try:
                btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                btn.click()
                logger.info(f"✅ Clicked cookie button: {selector}")
                time.sleep(1)
                break
            except:
                continue
        found = set()
        common_paths = [
            "/contact", "/contact-us", "/contactus", "/contact.html",
            "/contact.php", "/contact.aspx", "/en/contact", "/contact-form",
            "/get-in-touch", "/reach-out", "/connect", "/contacto", "/kontakt"
        ]
        for path in common_paths:
            contact_url = urljoin(base_url, path)
            if urlparse(contact_url).netloc == urlparse(base_url).netloc:
                found.add(contact_url)
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='contact'], a[href*='enquiry'], a[href*='connect']")
        for link in links:
            href = link.get_attribute("href") or ""
            if href and not href.startswith(("javascript:", "mailto:", "tel:")):
                full_url = urljoin(base_url, href)
                if urlparse(full_url).netloc == urlparse(base_url).netloc:
                    found.add(full_url)
        return list(found)
    except Exception as e:
        logger.error(f"Selenium find_contact error: {e}")
        return []

async def find_contact_pages(page, base_url):
    try:
        common_paths = [
            "/contact", "/contact-us", "/contactus", "/contact.html",
            "/contact.php", "/contact.aspx", "/en/contact", "/contact-form",
            "/get-in-touch", "/reach-out", "/connect", "/contacto", "/kontakt",
            "/contact-us.html", "/contact-us.php", "/contact-us.aspx",
            "/contact-us/", "/contactus/", "/contact-us-page", "/contact-page"
        ]
        found = set()
        for path in common_paths:
            contact_url = urljoin(base_url, path)
            if urlparse(contact_url).netloc == urlparse(base_url).netloc:
                found.add(contact_url)
        await page.goto(base_url, timeout=60000)
        await handle_popups(page)
        await handle_cookie_consent(page)
        try:
            contact_links = await page.query_selector_all(
                "a[href*='contact'], a:has-text('contact'), "
                "a[href*='enquiry'], a:has-text('enquiry'), "
                "a[href*='connect'], a:has-text('connect')"
            )
            for link in contact_links:
                href = await link.get_attribute("href") or ""
                if href and not href.startswith(("javascript:", "mailto:", "tel:")):
                    full_url = urljoin(base_url, href)
                    if urlparse(full_url).netloc == urlparse(base_url).netloc:
                        found.add(full_url)
            for pattern in CONTACT_NAV_PATTERNS:
                try:
                    links = await page.query_selector_all(f"xpath={pattern}")
                    for link in links:
                        href = await link.get_attribute("href") or ""
                        if href and not href.startswith(("javascript:", "mailto:", "tel:")):
                            full_url = urljoin(base_url, href)
                            if urlparse(full_url).netloc == urlparse(base_url).netloc:
                                found.add(full_url)
                except:
                    continue
            menu_items = await page.query_selector_all(
                "nav a, .menu a, .navigation a, .header-nav a, .footer-nav a"
            )
            for item in menu_items:
                text = (await item.text_content() or "").lower()
                href = await item.get_attribute("href") or ""
                if any(kw in text for kw in CONTACT_KEYWORDS) and href:
                    full_url = urljoin(base_url, href)
                    if urlparse(full_url).netloc == urlparse(base_url).netloc:
                        found.add(full_url)
            footer_links = await page.query_selector_all(
                "footer a, .footer a, .site-footer a"
            )
            for link in footer_links:
                text = (await link.text_content() or "").lower()
                href = await link.get_attribute("href") or ""
                if any(kw in text for kw in CONTACT_KEYWORDS) and href:
                    full_url = urljoin(base_url, href)
                    if urlparse(full_url).netloc == urlparse(base_url).netloc:
                        found.add(full_url)
        except Exception as e:
            logger.error(f"Error finding contact links: {str(e)}")
        return list(found)
    except Exception as e:
        logger.error(f"find_contact error: {e}")
        return []

async def try_fill_form(page, url, page_source, driver=None):
    try:
        await page.goto(url, timeout=60000)
        await handle_popups(page)
        await handle_cookie_consent(page)
        await asyncio.sleep(1)
        domain = urlparse(url).netloc
        mx_records = get_mx_records(domain)
        company, city = extract_company_and_city(page, page_source)
        emails = extract_emails(page_source)
        captcha = await page.query_selector("iframe[src*='captcha'], .g-recaptcha, #recaptcha")
        if captcha:
            logger.info(f"{url} → CAPTCHA detected, skipping")
            log_submission(url, "captcha_detected", {"company": company, "city": city, "mx_records": mx_records, "emails": emails})
            return False
        form_selectors = [
            "form", ".contact-form", "#contactForm", "#enquiryForm",
            ".wpcf7-form", ".gravity-form", ".forminator-form", ".elementor-form",
            "form[role='form']", ".gform_wrapper", ".contact-form-7", ".hs-form",
            ".form", ".webform", ".form-container", ".form-wrapper", ".form-contact",
            ".enquiry-form", "form[class*='contact']", "form[id*='contact']",
            "form[name*='contact']", "div[class*='form']"
        ]
        forms = []
        for selector in form_selectors:
            try:
                found_forms = await page.query_selector_all(selector)
                if found_forms:
                    forms.extend(found_forms)
            except:
                continue
        if not forms:
            logger.info(f"{url} → no forms found")
            log_submission(url, "no_forms", {"company": company, "city": city, "mx_records": mx_records, "emails": emails})
            return False
        logger.info(f"{url} → found {len(forms)} forms")
        for form in forms:
            inputs = await form.query_selector_all("input, textarea, select")
            filled = False
            for inp in inputs:
                t = (await inp.get_attribute("type") or "").lower()
                if t in ["hidden", "submit", "button", "image", "reset", "checkbox", "radio"]:
                    continue
                ph = (await inp.get_attribute("placeholder") or "").lower()
                nm = (await inp.get_attribute("name") or "").lower()
                id_attr = (await inp.get_attribute("id") or "").lower()
                lbl_text = ""
                if id_attr:
                    lbl = await page.query_selector(f'label[for="{id_attr}"]')
                    lbl_text = (await lbl.text_content() or "").lower() if lbl else ""
                context = None
                field_text = ph + nm + id_attr + lbl_text
                if any(x in field_text for x in ["mail", "e-mail", "email"]):
                    context = "email"
                elif any(x in field_text for x in ["name", "fullname", "first", "last", "fname", "lname"]):
                    context = "name"
                elif any(x in field_text for x in ["phone", "mobile", "tel", "telephone"]):
                    context = "phone"
                elif any(x in field_text for x in ["subject", "title", "reason", "topic"]):
                    context = "subject"
                elif any(x in field_text for x in ["address", "street", "city", "zip", "location", "country"]):
                    context = "address"
                elif any(x in field_text for x in ["message", "comment", "enquiry", "content", "details"]):
                    context = "message"
                elif await inp.evaluate("el => el.tagName") == "TEXTAREA":
                    context = "message"
                if not context:
                    continue
                val = {
                    "email": EMAIL,
                    "name": NAME,
                    "phone": PHONE,
                    "subject": SUBJECT,
                    "address": ADDRESS,
                    "message": MESSAGE
                }[context]
                try:
                    await inp.fill(val)
                    logger.info(f"✍️ {context} field filled")
                except:
                    await page.keyboard.type(val, delay=random.randint(50, 150))
                    logger.info(f"⌨️ Typed {context} value")
                filled = True
            checkboxes = await form.query_selector_all("input[type='checkbox']")
            for cb in checkboxes:
                parent = await cb.query_selector("xpath=..")
                if parent:
                    parent_text = (await parent.text_content() or "").lower()
                    if any(term in parent_text for term in TERMS_KEYWORDS):
                        if not await cb.is_checked():
                            await cb.check()
                            logger.info("✅ Checked terms checkbox")
                            filled = True
            if not filled:
                logger.info("⚠️ No fillable fields found in form")
                continue
            submit_selectors = [
                "input[type=submit]", "button[type=submit]", "button:has-text('Send')",
                "button:has-text('Submit')", "button:has-text('Contact')",
                "button:has-text('Enquire')", "button:has-text('Reach Out')",
                "button:has-text('Send Message')", "button:has-text('Request Quote')",
                "button:has-text('Get in Touch')", "button:has-text('Submit Form')",
                "button:has-text('Send Enquiry')", "button:has-text('Submit Request')"
            ]
            submitted = False
            for selector in submit_selectors:
                try:
                    btn = await form.query_selector(selector)
                    if btn:
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        try:
                            await page.wait_for_navigation(timeout=5000)
                        except:
                            await asyncio.sleep(5)
                        submitted = True
                        break
                except:
                    continue
            if not submitted:
                try:
                    await form.evaluate("form => form.submit()")
                    await asyncio.sleep(5)
                    submitted = True
                except:
                    pass
            await asyncio.sleep(2)
            img = await page.screenshot()
            current_url = page.url
            html = (await page.content()).lower()
            success_indicators = [
                "thank you", "submitted", "we'll contact", "success",
                "received", "confirmation", "successfully", "message sent",
                "enquiry received", "contact received", "form submitted",
                "thank you for your message", "thank you for contacting"
            ]
            data = {"company": company, "city": city, "mx_records": mx_records, "emails": emails}
            if submitted:
                if any(x in current_url for x in ["thank", "success", "confirmation"]) or any(x in html for x in success_indicators):
                    logger.info("✅ Form submitted successfully")
                    send_to_telegram(img, f"Success: {url}\nNew URL: {current_url}\nData: {data}")
                    log_submission(url, "success", data)
                else:
                    logger.info("⚠️ Form submitted but success not confirmed")
                    send_to_telegram(img, f"Submitted/Unconfirmed: {url}\nCurrent URL: {current_url}\nData: {data}")
                    log_submission(url, "unconfirmed", data)
                return True
            else:
                logger.info("⚠️ Form filled but no submit button found")
                send_to_telegram(img, f"Filled w/o submit: {url}\nData: {data}")
                log_submission(url, "no_submit", data)
                return True
        return False
    except PlaywrightTimeoutError:
        logger.error("Timeout on " + url)
        try:
            img = await page.screenshot()
            send_to_telegram(img, f"Timeout error: {url}\nData: {data}")
            log_submission(url, "timeout", data)
        except:
            pass
    except Exception as e:
        logger.error(f"form fill error: {e}")
        try:
            img = await page.screenshot()
            send_to_telegram(img, f"Error: {url}\n{str(e)}\nData: {data}")
            log_submission(url, "error", data)
        except:
            pass
    return False

def duckduckgo_search_with_retry(query, max_results=5, retries=3, backoff_factor=2):
    for attempt in range(retries):
        try:
            logger.info(f"Searching DuckDuckGo for: '{query}'")
            with DDGS() as ddgs:
                results = []
                for r in ddgs.text(query):
                    results.append(r["href"])
                    if len(results) >= max_results:
                        break
                return results
        except Exception as e:
            wait_time = backoff_factor ** (attempt + 1) + random.uniform(1, 5)
            logger.warning(f"Search error: {str(e)}. Waiting {wait_time:.1f}s before retry {attempt+1}/{retries}")
            time.sleep(wait_time)
    logger.error(f"Failed to search '{query}' after {retries} retries")
    return []

async def main():
    async with async_playwright() as pw:
        driver = start_undetected_driver()
        browser = await pw.chromium.launch(
            headless=not DEBUG,
            args=[
                "--window-size=1280,720",
                "--disable-blink-features=AutomationControlled",
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ],
            channel="chrome"
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.60 Safari/537.36"
        )
        page = await context.new_page()
        try:
            while True:
                for kw in KEYWORDS:
                    logger.info(f"🔍 Searching: {kw}")
                    try:
                        search_results = duckduckgo_search_with_retry(kw, max_results=5)
                        if not search_results:
                            logger.warning(f"No results found for '{kw}'")
                            continue
                        for res in search_results:
                            try:
                                domain = urlparse(res).netloc
                                if domain in visited_domains:
                                    logger.info(f"⏩ Skipping already processed domain: {domain}")
                                    continue
                                visited_domains.add(domain)
                                base = f"{urlparse(res).scheme}://{domain}"
                                logger.info(f"🌐 Processing domain: {domain}")
                                contact_pages = []
                                if driver:
                                    contact_pages = await find_contact_pages_selenium(driver, base)
                                if not contact_pages:
                                    contact_pages = await find_contact_pages(page, base)
                                    if not contact_pages:
                                        contact_url = urljoin(base, "/contact")
                                        logger.info(f"🔄 Trying fallback contact page: {contact_url}")
                                        contact_pages = [contact_url]
                                for cp in contact_pages:
                                    logger.info(f"📝 Attempting contact page: {cp}")
                                    page_source = driver.page_source if driver and driver.current_url == cp else await page.content()
                                    if await try_fill_form(page, cp, page_source, driver):
                                        break
                                await asyncio.sleep(random.uniform(10, 20))
                            except Exception as e:
                                logger.error(f"Error processing {res}: {e}")
                                continue
                        if driver:
                            try:
                                driver.quit()
                                driver = start_undetected_driver()
                            except:
                                driver = None
                    except Exception as e:
                        logger.error(f"Search error for '{kw}': {e}")
                wait_time = random.randint(45, 90)
                logger.info(f"🔄 Completed keyword cycle, restarting in {wait_time} seconds")
                await asyncio.sleep(wait_time)
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
