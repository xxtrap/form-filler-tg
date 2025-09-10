import asyncio
import random
import re
import logging
import sys
import time
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright
from PIL import Image
import io
from duckduckgo_search import DDGS
import dns.resolver
from faker import Faker
from twocaptcha import TwoCaptcha
from telegram import Bot

# === CONFIG ===
BOT_TOKEN = "7619040891:AAF9pfQQme32XvhTfUb97jzky5w4ZEaBzwc"
CHAT_ID = "5172045930"
CAPTCHA_API_KEY = "71a87dcb7b9f01c390a0c26357a14788"
DEBUG = False
BLACKLIST_FILE = "blacklist.txt"

NAME = "Kevin Fang"
EMAIL = "kevandcoceo@hotmail.com"
PHONE = "+365433225"
SUBJECT = "Urgent Legal Inquiry"
MESSAGE_VARIATIONS = [
    "Hi I'm Kevin, I run a concierge service and I get a few issues with one of my clients, a politician and ive been subpeoned i need someone to represewnt me i have done nothing wrong kindly reach oput via email as im not in the states currently",
    "Hello, I'm Kevin, facing a business dispute with a client (politician). I'm innocent and need urgent representation. Please contact me via email ASAP.",
    "Hi, Kevin here. My concierge service has a client issue (politician, subpoena). I'm not at fault, need legal help fast. Email me, I'm abroad."
]
KEYWORDS = [
    "lawyers in California",
    "business dispute lawyers California",
    "criminal lawyers California",
    "litigation attorneys CA"
]
CONTACT_KEYWORDS = ["contact", "enquiry", "connect", "getintouch", "message", "reach", "touch"]
COOKIE_SELECTORS = [
    "#cookie-consent", ".cookie-banner", "#cookie-notice", "#cookiePolicy",
    "#acceptCookies", ".btn-cookies", ".cookie-accept", ".cookie-ok", "#gdpr-consent",
    ".cookie-agree", "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    ".cc-btn", ".cookie-notice-actions button", "button:has-text('Accept')",
    "button:has-text(' Agree')", "button:has-text('Allow')", "button:has-text('OK')",
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
FORM_SELECTORS = [
    "form", ".contact-form", "#contactForm", "#enquiryForm",
    ".wpcf7-form", ".gravity-form", ".forminator-form", ".elementor-form",
    "form[role='form']", ".gform_wrapper", ".contact-form-7",
    ".hs-form", ".form", ".webform", ".form-container",
    ".form-wrapper", ".form-contact", ".enquiry-form",
    "form[class*='contact']", "form[id*='contact']", "form[name*='contact']",
    "div[class*='form']"
]
SUBMIT_SELECTORS = [
    "input[type='submit']", "button[type='submit']", "button:has-text('Send')",
    "button:has-text('Submit')", "button:has-text('Contact')",
    "button:has-text('Enquire')", "button:has-text('Reach Out')",
    "button:has-text('Send Message')", "button:has-text('Request Quote')",
    "button:has-text('Get in Touch')", "button:has-text('Submit Form')",
    "button:has-text('Send Enquiry')", "button:has-text('Submit Request')"
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("lead_scraper")
visited_domains = set()
fake = Faker()
captcha_client = TwoCaptcha(CAPTCHA_API_KEY)

# Load blacklist
try:
    with open(BLACKLIST_FILE, 'r') as f:
        blacklist = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    blacklist = ["microsoft", "outlook", "yelp.com", "avvo.com", "justia.com", "linkedin.com"]
    logger.warning("Blacklist file not found, using defaults")

async def send_to_telegram(image_bytes, caption):
    try:
        if not image_bytes or len(image_bytes) < 1024:
            logger.error("Invalid image for Telegram")
            return
        img = Image.open(io.BytesIO(image_bytes))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        bot = Bot(token=BOT_TOKEN)
        await bot.send_photo(chat_id=CHAT_ID, photo=buf, caption=caption[:1024])
        logger.info("Telegram: Message sent")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

async def handle_popups(page):
    for selector in POPUP_SELECTORS:
        try:
            popup = await page.query_selector(selector, timeout=5000)
            if popup:
                close_btn = await popup.query_selector(
                    ".close, .dismiss, [aria-label='Close'], [aria-label='Dismiss'], "
                    "[title='Close'], [title='Dismiss'], .btn-close, .popup-close, "
                    ".modal-close, .close-button, .close-icon, "
                    "button:has-text('Close'), button:has-text('Dismiss'), "
                    "button:has-text('No thanks'), button:has-text('Maybe later'), "
                    "button:has-text('Not now'), button:has-text('Decline')"
                )
                if close_btn:
                    await close_btn.scroll_into_view_if_needed()
                    await close_btn.click(timeout=5000)
                    logger.info(f"Closed popup: {selector}")
                    await asyncio.sleep(1)
                    return True
        except:
            pass
    return False

async def handle_cookie_consent(page):
    for _ in range(3):
        for sel in COOKIE_SELECTORS:
            try:
                btn = await page.query_selector(f"{sel}:visible", timeout=5000)
                if btn:
                    await btn.scroll_into_view_if_needed()
                    await btn.click(timeout=5000)
                    logger.info(f"Clicked cookie button: {sel}")
                    await asyncio.sleep(1)
                    return True
            except:
                pass
        await asyncio.sleep(1)
    return False

async def get_mx_records(domain):
    try:
        answers = dns.resolver.resolve(domain, 'MX')
        return [str(r.exchange) for r in answers]
    except:
        return ["No MX records"]

async def extract_leads(page):
    try:
        content = (await page.content()).lower()
        emails = list(set(re.findall(r"[a-z0-9\.\-+_]+@[a-z0-9\.\-+_]+\.[a-z]+", content)))
        phones = list(set(re.findall(r"\+?\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}", content)))
        addresses = list(set(re.findall(r"\d+\s+[A-Za-z\s]+,\s*[A-Za-z\s]+,\s*[A-Z]{2}\s*\d{5}", content)))
        return {"emails": emails, "phones": phones, "addresses": addresses}
    except Exception as e:
        logger.error(f"Lead extraction error: {e}")
        return {"emails": [], "phones": [], "addresses": []}

async def find_contact_pages(page, base_url):
    contact_urls = set()
    try:
        await page.goto(base_url, timeout=15000)
        await handle_popups(page)
        await handle_cookie_consent(page)

        common_paths = [
            "/contact", "/contact-us", "/contactus", "/contact.html",
            "/contact.php", "/contact.aspx", "/en/contact", "/contact-form",
            "/get-in-touch", "/reach-out", "/connect", "/contacto", "/kontakt",
            "/contact-us.html", "/contact-us.php", "/contact-us.aspx",
            "/contact-us/", "/contactus/", "/contact-us-page", "/contact-page"
        ]
        for path in common_paths:
            contact_url = urljoin(base_url, path)
            if urlparse(contact_url).netloc == urlparse(base_url).netloc:
                contact_urls.add(contact_url)

        contact_links = await page.query_selector_all(
            "a[href*='contact'], a:has-text('contact'), "
            "a[href*='enquiry'], a:has-text('enquiry'), "
            "a[href*='connect'], a:has-text('connect'), "
            "a[href*='form'], a:has-text('inquiry')"
        )
        for link in contact_links:
            href = await link.get_attribute("href") or ""
            if href and not href.startswith(("javascript:", "mailto:", "tel:")):
                full_url = urljoin(base_url, href)
                if urlparse(full_url).netloc == urlparse(base_url).netloc:
                    contact_urls.add(full_url)

        for pattern in CONTACT_NAV_PATTERNS:
            try:
                links = await page.query_selector_all(f"xpath={pattern}")
                for link in links:
                    href = await link.get_attribute("href") or ""
                    if href and not href.startswith(("javascript:", "mailto:", "tel:")):
                        full_url = urljoin(base_url, href)
                        if urlparse(full_url).netloc == urlparse(base_url).netloc:
                            contact_urls.add(full_url)
            except:
                pass

        menu_items = await page.query_selector_all(
            "nav a, .menu a, .navigation a, .header-nav a, .footer-nav a"
        )
        for item in menu_items:
            text = (await item.text_content() or "").lower()
            href = await item.get_attribute("href") or ""
            if any(kw in text for kw in CONTACT_KEYWORDS) and href:
                full_url = urljoin(base_url, href)
                if urlparse(full_url).netloc == urlparse(base_url).netloc:
                    contact_urls.add(full_url)

        buttons = await page.query_selector_all(
            "button:has-text('Contact'), button:has-text('Enquire'), "
            "button:has-text('Get in Touch'), a:has-text('Enquire Now')"
        )
        for btn in buttons:
            try:
                await btn.scroll_into_view_if_needed()
                await btn.click(timeout=5000)
                await asyncio.sleep(2)
                form = await page.query_selector(FORM_SELECTORS[0])
                if form:
                    contact_urls.add(page.url)
            except:
                pass

        return list(contact_urls)
    except Exception as e:
        logger.error(f"find_contact error: {e}")
        return list(contact_urls)

async def solve_recaptcha(page):
    try:
        recaptcha = await page.query_selector("[data-sitekey]", timeout=5000)
        if not recaptcha:
            return None
        sitekey = await recaptcha.get_attribute("data-sitekey")
        result = captcha_client.recaptcha(sitekey=sitekey, url=page.url)
        token = result["code"]
        await page.evaluate(f'document.getElementById("g-recaptcha-response").innerHTML = "{token}";')
        logger.info("reCAPTCHA solved")
        return token
    except Exception as e:
        logger.error(f"reCAPTCHA error: {e}")
        return None

async def try_fill_form(page, url, company, domain, keyword):
    status = "No forms found"
    try:
        await page.goto(url, timeout=15000)
        await handle_popups(page)
        await handle_cookie_consent(page)
        await asyncio.sleep(1)

        forms = []
        for selector in FORM_SELECTORS:
            found_forms = await page.query_selector_all(selector)
            forms.extend(found_forms)

        if not forms:
            logger.info(f"{url} → no forms found")
            img = await page.screenshot(full_page=True)
            leads = await extract_leads(page)
            await send_to_telegram(img, f"Company: {company}\nDomain: {domain}\nKeyword: {keyword}\nMX: {', '.join(await get_mx_records(domain))}\nEmails: {', '.join(leads['emails'])}\nPhones: {', '.join(leads['phones'])}\nAddresses: {', '.join(leads['addresses'])}\nURL: {url}\nStatus: {status}")
            return {"url": url, "status": status}

        logger.info(f"{url} → found {len(forms)} forms")
        for form in forms:
            filled = False
            inputs = await form.query_selector_all("input, textarea, select")
            for inp in inputs:
                input_type = (await inp.get_attribute("type") or "").lower()
                if input_type in ["hidden", "submit", "button", "image", "reset"]:
                    continue

                placeholder = (await inp.get_attribute("placeholder") or "").lower()
                name = (await inp.get_attribute("name") or "").lower()
                input_id = (await inp.get_attribute("id") or "").lower()
                label = await page.query_selector(f"label[for='{input_id}']")
                label_text = (await label.text_content() or "").lower() if label else ""
                field_text = placeholder + name + input_id + label_text

                context = None
                value = None
                if any(x in field_text for x in ["mail", "e-mail", "email"]):
                    context, value = "email", EMAIL
                elif any(x in field_text for x in ["name", "fullname", "first", "last", "fname", "lname"]):
                    context, value = "name", NAME
                elif any(x in field_text for x in ["phone", "mobile", "tel", "telephone"]):
                    context, value = "phone", PHONE
                elif any(x in field_text for x in ["subject", "title", "reason", "topic"]):
                    context, value = "subject", SUBJECT
                elif any(x in field_text for x in ["message", "comment", "enquiry", "content", "details", "challenge"]) or (await inp.evaluate("el => el.tagName")).lower() == "textarea":
                    context, value = "message", random.choice(MESSAGE_VARIATIONS)
                elif (await inp.evaluate("el => el.tagName")).lower() == "select":
                    options = await inp.query_selector_all("option")
                    if len(options) > 1:
                        value = await options[random.randint(1, len(options) - 1)].get_attribute("value")
                elif input_type == "number" or "budget" in field_text:
                    value = str(fake.random_int(100, 10000))
                elif input_type == "date":
                    value = fake.date_this_year().strftime("%Y-%m-%d")
                elif any(x in field_text for x in ["address", "street", "zip", "location", "country"]):
                    value = fake.street_address()
                elif any(x in field_text for x in ["company", "business", "organization"]):
                    value = fake.company()
                elif "city" in field_text:
                    value = fake.city()
                else:
                    value = fake.sentence()

                if value:
                    try:
                        await inp.click(timeout=5000)
                        if (await inp.evaluate("el => el.tagName")).lower() == "select":
                            await inp.select_option(value)
                        else:
                            await inp.fill("")
                            await page.keyboard.type(value, delay=random.randint(50, 150))
                            await page.keyboard.press("Tab")
                        logger.info(f"Filled {context or 'unknown'} field: {value}")
                        filled = True
                    except:
                        continue

            checkboxes = await form.query_selector_all("input[type='checkbox']:not([type='hidden'])")
            for cb in checkboxes:
                if not await cb.is_checked():
                    try:
                        await cb.check()
                        logger.info("Checked checkbox")
                        filled = True
                    except:
                        continue

            if not filled:
                status = "No fillable fields"
                img = await page.screenshot(full_page=True)
                leads = await extract_leads(page)
                await send_to_telegram(img, f"Company: {company}\nDomain: {domain}\nKeyword: {keyword}\nMX: {', '.join(await get_mx_records(domain))}\nEmails: {', '.join(leads['emails'])}\nPhones: {', '.join(leads['phones'])}\nAddresses: {', '.join(leads['addresses'])}\nURL: {url}\nStatus: {status}")
                continue

            recaptcha_token = await solve_recaptcha(page)
            if recaptcha_token:
                status = "CAPTCHA solved"
            elif await page.query_selector(".h-captcha, [data-hcaptcha-container], [data-sitekey]"):
                status = "CAPTCHA detected, skipped"
                img = await page.screenshot(full_page=True)
                leads = await extract_leads(page)
                await send_to_telegram(img, f"Company: {company}\nDomain: {domain}\nKeyword: {keyword}\nMX: {', '.join(await get_mx_records(domain))}\nEmails: {', '.join(leads['emails'])}\nPhones: {', '.join(leads['phones'])}\nAddresses: {', '.join(leads['addresses'])}\nURL: {url}\nStatus: {status}")
                continue

            submitted = False
            for selector in SUBMIT_SELECTORS:
                try:
                    btn = await form.query_selector(selector)
                    if btn:
                        await btn.scroll_into_view_if_needed()
                        await btn.click(timeout=5000)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=5000)
                        except:
                            await asyncio.sleep(3)
                        submitted = True
                        break
                except:
                    continue

            if not submitted:
                try:
                    await form.evaluate("form => form.submit()")
                    await asyncio.sleep(3)
                    submitted = True
                except:
                    pass

            img = await page.screenshot(full_page=True)
            html = (await page.content()).lower()
            success_indicators = ["thank you", "submitted", "we'll contact", "success", "received", "confirmation", "successfully", "message sent"]
            leads = await extract_leads(page)
            if submitted:
                if any(x in page.url for x in ["thank", "success", "confirmation"]) or any(x in html for x in success_indicators):
                    status = "Submitted successfully"
                else:
                    status = "Submitted, unconfirmed"
            else:
                status = "Filled, no submit button"
            await send_to_telegram(img, f"Company: {company}\nDomain: {domain}\nKeyword: {keyword}\nMX: {', '.join(await get_mx_records(domain))}\nEmails: {', '.join(leads['emails'])}\nPhones: {', '.join(leads['phones'])}\nAddresses: {', '.join(leads['addresses'])}\nURL: {url}\nStatus: {status}")
            with open("submissions.json", "a") as f:
                import json
                json.dump({
                    "company": company,
                    "domain": domain,
                    "keyword": keyword,
                    "mx": await get_mx_records(domain),
                    "emails": leads["emails"],
                    "phones": leads["phones"],
                    "addresses": leads["addresses"],
                    "url": url,
                    "status": status,
                    "timestamp": time.ctime()
                }, f)
                f.write("\n")
            return {"url": url, "status": status}
    except Exception as e:
        status = f"Error: {e}"
        img = await page.screenshot(full_page=True)
        leads = await extract_leads(page)
        await send_to_telegram(img, f"Company: {company}\nDomain: {domain}\nKeyword: {keyword}\nMX: {', '.join(await get_mx_records(domain))}\nEmails: {', '.join(leads['emails'])}\nPhones: {', '.join(leads['phones'])}\nAddresses: {', '.join(leads['addresses'])}\nURL: {url}\nStatus: {status}")
        with open("submissions.json", "a") as f:
            import json
            json.dump({
                "company": company,
                "domain": domain,
                "keyword": keyword,
                "mx": await get_mx_records(domain),
                "emails": leads["emails"],
                "phones": leads["phones"],
                "addresses": leads["addresses"],
                "url": url,
                "status": status,
                "timestamp": time.ctime()
            }, f)
            f.write("\n")
        return {"url": url, "status": status}

async def search_engine(query, engine, max_results=5):
    try:
        if engine == "duckduckgo":
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=max_results)
                return [r["href"] for r in results]
        elif engine in ["google", "bing"]:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=not DEBUG)
                page = await browser.new_page()
                url = f"https://www.{'google' if engine == 'google' else 'bing'}.com/search?q={query}"
                await page.goto(url, timeout=15000)
                await page.wait_for_selector("h3" if engine == "google" else ".b_algo h2", timeout=10000)
                links = await page.query_selector_all("a > h3" if engine == "google" else ".b_algo h2 a")
                results = [await link.get_attribute("href") for link in links[:max_results] if await link.get_attribute("href")]
                await browser.close()
                return results
        return []
    except Exception as e:
        logger.error(f"Search error on {engine}: {e}")
        return []

async def main():
    async with async_playwright() as p:
        while True:
            browser = await p.chromium.launch(
                headless=not DEBUG,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--ignore-certificate-errors",
                    "--user-agent=" + fake.user_agent()
                ]
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=fake.user_agent()
            )
            try:
                for kw in sorted(KEYWORDS, key=lambda x: random.random()):
                    logger.info(f"Searching: {kw}")
                    for engine in ["duckduckgo", "google", "bing"]:
                        search_results = await search_engine(kw, engine, 5)
                        if not search_results:
                            logger.warning(f"No results for '{kw}' on {engine}")
                            continue
                        for res in search_results:
                            domain = urlparse(res).netloc
                            if domain in visited_domains or any(black in domain for black in blacklist):
                                logger.info(f"Skipping: {domain}")
                                continue
                            visited_domains.add(domain)
                            base = f"{urlparse(res).scheme}://{domain}"
                            logger.info(f"Processing: {domain}")
                            page = await context.new_page()
                            try:
                                await page.goto(base, timeout=15000)
                                company = await page.title() or "Unknown"
                                content = (await page.content()).lower()
                                if not any(kw.lower() in content for kw in ["lawyer", "attorney", "law firm"]):
                                    logger.info(f"Irrelevant: {domain}")
                                    continue
                                contact_pages = await find_contact_pages(page, base)
                                if not contact_pages:
                                    contact_pages = [urljoin(base, "/contact"), urljoin(base, "/contact-us")]
                                contact_status = []
                                leads = await extract_leads(page)
                                for cp in contact_pages:
                                    result = await try_fill_form(page, cp, company, domain, kw)
                                    contact_status.append(result)
                                caption = f"Company: {company}\nDomain: {domain}\nKeyword: {kw}\nMX: {', '.join(await get_mx_records(domain))}\nEmails: {', '.join(leads['emails'])}\nPhones: {', '.join(leads['phones'])}\nAddresses: {', '.join(leads['addresses'])}\nContact Pages:\n" + "\n".join([f"- {r['url']}: {r['status']}" for r in contact_status])
                                logger.info(caption)
                                with open("submissions.json", "a") as f:
                                    import json
                                    json.dump({
                                        "company": company,
                                        "domain": domain,
                                        "keyword": kw,
                                        "mx": await get_mx_records(domain),
                                        "emails": leads["emails"],
                                        "phones": leads["phones"],
                                        "addresses": leads["addresses"],
                                        "contactStatus": contact_status,
                                        "timestamp": time.ctime()
                                    }, f)
                                    f.write("\n")
                            except Exception as e:
                                logger.error(f"Error processing {domain}: {e}")
                            finally:
                                await page.close()
                                await asyncio.sleep(random.uniform(1, 3))
                        await context.clear_cookies()
                        await context.clear_permissions()
            except Exception as e:
                logger.error(f"Main error: {e}")
            finally:
                await browser.close()
                wait_time = random.uniform(30, 90)
                logger.info(f"Break for {wait_time:.1f} seconds")
                await asyncio.sleep(wait_time)

if __name__ == "__main__":
    asyncio.run(main())
