import asyncio, random, re, logging, sys, time
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import requests, io
from PIL import Image
from urllib.parse import urljoin, urlparse
from duckduckgo_search import DDGS

# === CONFIG ===
BOT_TOKEN = "7935254151:AAHHN3zAfvCgw6RQ7IED8ez6lHmaxiJAtk"
CHAT_ID = "5172045930"
DEBUG = False

NAME = "Kevin Fang"
EMAIL = "kevandcoceo@hotmail.com"
PHONE = "+365433225"
ADDRESS = "123 Main St, New York, NY 10001"
SUBJECT = "Partnership with Concierge"
MESSAGE = "Hi I'm Kevin, I run a concierge service and I get a lot of clients looking to take trips in July and August. Please contact me to discuss a potential partnership."

KEYWORDS = [
    "private jet charter USA contact",
    "luxury yacht rental Dubai enquiry",
    "private aviation charter Europe contact"
]
CONTACT_KEYWORDS = ["contact", "enquiry", "connect", "getintouch", "message", "reach", "touch"]

# Enhanced cookie selectors (30+ variations)
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

# Terms checkbox detection keywords
TERMS_KEYWORDS = ["terms", "conditions", "privacy", "policy", "agree", "accept", "gdpr", "consent"]

# Popup/dialog selectors
POPUP_SELECTORS = [
    ".modal", ".popup", ".dialog", ".lightbox", "#modal", "#popup",
    "div[role='dialog']", "div[class*='modal']", "div[class*='popup']",
    ".overlay", ".notice", ".alert", ".notification", ".interstitial",
    ".slide-in", ".banner", ".ad-container", ".newsletter-popup"
]

# Navigation patterns for contact pages
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

# Track visited domains to avoid duplicates
visited_domains = set()

def send_to_telegram(image_bytes, caption):
    try:
        # Validate image
        if not image_bytes or len(image_bytes) < 1024:
            logger.error("Invalid image for Telegram")
            return
            
        # Create image
        img = Image.open(io.BytesIO(image_bytes))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        
        # Prepare request
        files = {"photo": ("screenshot.jpg", buf.getvalue())}
        data = {"chat_id": CHAT_ID, "caption": caption[:1024]}  # Truncate long captions
        
        # Send with timeout
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

# -----------------------------------
# FUNCTION: handle popups and banners
# -----------------------------------
async def handle_popups(page):
    # Try to close any popups/modals
    for selector in POPUP_SELECTORS:
        try:
            popup = await page.query_selector(selector)
            if popup:
                # Look for close buttons in the popup
                close_btn = await popup.query_selector(
                    ".close, .dismiss, [aria-label='Close'], [aria-label='Dismiss'], "
                    "[title='Close'], [title='Dismiss'], .btn-close, .popup-close, "
                    ".modal-close, .close-button, .close-icon"
                )
                
                if not close_btn:
                    # Try text-based close buttons
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

# -----------------------------------
# FUNCTION: handle cookies (enhanced with retries)
# -----------------------------------
async def handle_cookie_consent(page):
    # Try multiple times as cookies might appear after delay
    for attempt in range(3):
        for sel in COOKIE_SELECTORS:
            try:
                # Try visible buttons first
                btn = await page.query_selector(f"{sel}:visible")
                if not btn:
                    # Fallback to all elements matching selector
                    btn = await page.query_selector(sel)
                
                if btn:
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    logger.info(f"✅ Clicked cookie button using selector: {sel}")
                    await asyncio.sleep(1)
                    return True
            except Exception as e:
                logger.debug(f"Cookie click failed on {sel}: {str(e)}")
        
        # Wait before next attempt
        await asyncio.sleep(1)
    return False

# -----------------------------------
# FUNCTION: find contact pages (completely overhauled)
# -----------------------------------
async def find_contact_pages(page, base_url):
    try:
        # Try direct contact page paths first
        common_paths = [
            "/contact", "/contact-us", "/contactus", "/contact.html", 
            "/contact.php", "/contact.aspx", "/en/contact", "/contact-form",
            "/get-in-touch", "/reach-out", "/connect", "/contacto", "/kontakt",
            "/contact-us.html", "/contact-us.php", "/contact-us.aspx",
            "/contact-us/", "/contactus/", "/contact-us-page", "/contact-page"
        ]
        
        # Try each common path directly
        found = set()
        for path in common_paths:
            contact_url = urljoin(base_url, path)
            if urlparse(contact_url).netloc == urlparse(base_url).netloc:
                found.add(contact_url)
        
        # Now try to navigate the site to find contact pages
        await page.goto(base_url, timeout=60000)
        await handle_popups(page)
        await handle_cookie_consent(page)
        
        # Try to find contact links using multiple methods
        try:
            # Method 1: CSS selectors
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
            
            # Method 2: XPath patterns
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
            
            # Method 3: Navigation menus
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
            
            # Method 4: Footer links
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

# -----------------------------------
# SMART FORM FILLING (enhanced with all requirements)
# -----------------------------------
async def try_fill_form(page, url):
    try:
        await page.goto(url, timeout=60000)
        await handle_popups(page)
        await handle_cookie_consent(page)
        
        # Wait for page to settle
        await asyncio.sleep(1)
        
        # Enhanced form selectors
        form_selectors = [
            "form", 
            ".contact-form", 
            "#contactForm", 
            "#enquiryForm",
            ".wpcf7-form", 
            ".gravity-form", 
            ".forminator-form", 
            ".elementor-form",
            "form[role='form']",
            ".gform_wrapper",
            ".contact-form-7",
            ".hs-form",  # HubSpot
            ".form",     # Generic
            ".webform",  # Drupal
            ".form-container",
            ".form-wrapper",
            ".form-contact",
            ".enquiry-form",
            "form[class*='contact']",
            "form[id*='contact']",
            "form[name*='contact']",
            "div[class*='form']"  # Sometimes forms are in div containers
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
            return False
        else:
            logger.info(f"{url} → found {len(forms)} forms")

        for form in forms:
            inputs = await form.query_selector_all("input, textarea, select")
            filled = False
            
            for inp in inputs:
                t = (await inp.get_attribute("type") or "").lower()
                if t in ["hidden", "submit", "button", "image", "reset", "checkbox", "radio"]:
                    continue
                    
                # Get context from multiple attributes
                ph = (await inp.get_attribute("placeholder") or "").lower()
                nm = (await inp.get_attribute("name") or "").lower()
                id_attr = (await inp.get_attribute("id") or "").lower()
                lbl_text = ""
                
                # Get label text if exists
                if id_attr:
                    lbl = await page.query_selector(f'label[for="{id_attr}"]')
                    lbl_text = (await lbl.text_content() or "").lower() if lbl else ""
                
                # Determine field context
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
                    
                # Get appropriate value
                val = {
                    "email": EMAIL,
                    "name": NAME,
                    "phone": PHONE,
                    "subject": SUBJECT,
                    "address": ADDRESS,
                    "message": MESSAGE
                }[context]
                
                # Handle different input types
                tag_name = await inp.evaluate("el => el.tagName")
                if tag_name == "SELECT":
                    try:
                        # Get all options
                        options = await inp.query_selector_all("option")
                        if len(options) > 1:
                            # Try to select the second option
                            await options[1].click()
                            logger.info(f"🔘 Selected second dropdown option")
                        else:
                            await inp.select_option(val)
                            logger.info(f"🔘 Selected dropdown value")
                    except:
                        # Fallback to typing if direct selection fails
                        await inp.focus()
                        await page.keyboard.type(val, delay=100)
                        logger.info(f"⌨️ Typed dropdown value")
                else:
                    try:
                        await inp.fill(val)
                        logger.info(f"✍️ {context} field filled")
                    except:
                        await page.keyboard.type(val, delay=random.randint(50, 150))
                        logger.info(f"⌨️ Typed {context} value")
                
                filled = True
                
            # Handle terms checkboxes
            checkboxes = await form.query_selector_all("input[type='checkbox']")
            for cb in checkboxes:
                # Check if nearby text contains terms keywords
                parent = await cb.query_selector("xpath=..")  # Get parent element
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
                
            # Submit handling with multiple attempts
            submit_selectors = [
                "input[type=submit]", 
                "button[type=submit]", 
                "button:has-text('Send')",
                "button:has-text('Submit')",
                "button:has-text('Contact')",
                "button:has-text('Enquire')",
                "button:has-text('Reach Out')",
                "button:has-text('Send Message')",
                "button:has-text('Request Quote')",
                "button:has-text('Get in Touch')",
                "button:has-text('Submit Form')",
                "button:has-text('Send Enquiry')",
                "button:has-text('Submit Request')"
            ]
            
            submitted = False
            for selector in submit_selectors:
                try:
                    btn = await form.query_selector(selector)
                    if btn:
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        
                        # Wait for navigation or 5 seconds
                        try:
                            await page.wait_for_navigation(timeout=5000)
                        except:
                            await asyncio.sleep(5)  # Wait 5 seconds if no navigation
                            
                        submitted = True
                        break
                except:
                    continue
                    
            if not submitted:
                # Fallback to form submission
                try:
                    await form.evaluate("form => form.submit()")
                    await asyncio.sleep(5)  # Wait 5 seconds after submission
                    submitted = True
                except:
                    pass
            
            # Wait for any post-submission changes
            await asyncio.sleep(2)
            img = await page.screenshot()
            
            # Verify submission by URL change or content
            current_url = page.url
            html = (await page.content()).lower()
            
            success_indicators = [
                "thank you", "submitted", "we'll contact", "success", 
                "received", "confirmation", "successfully", "message sent",
                "enquiry received", "contact received", "form submitted",
                "thank you for your message", "thank you for contacting"
            ]
            
            if submitted:
                if any(x in current_url for x in ["thank", "success", "confirmation"]) or any(x in html for x in success_indicators):
                    logger.info("✅ Form submitted successfully")
                    send_to_telegram(img, f"Success: {url}\nNew URL: {current_url}")
                else:
                    logger.info("⚠️ Form submitted but success not confirmed")
                    send_to_telegram(img, f"Submitted/Unconfirmed: {url}\nCurrent URL: {current_url}")
                return True
            else:
                logger.info("⚠️ Form filled but no submit button found")
                send_to_telegram(img, f"Filled w/o submit: {url}")
                return True
                
        return False
    except PlaywrightTimeoutError:
        logger.error("Timeout on " + url)
        try:
            img = await page.screenshot()
            send_to_telegram(img, f"Timeout error: {url}")
        except:
            pass
    except Exception as e:
        logger.error(f"form fill error: {e}")
        try:
            img = await page.screenshot()
            send_to_telegram(img, f"Error: {url}\n{str(e)}")
        except:
            pass
    return False

# -----------------------------------
# DUCKDUCKGO SEARCH WITH RETRIES
# -----------------------------------
def duckduckgo_search_with_retry(query, max_results=5, retries=3, backoff_factor=2):
    """Custom DuckDuckGo search function with retries and delays"""
    for attempt in range(retries):
        try:
            # Perform search
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

# -----------------------------------
# MAIN EXECUTION FLOW (continuous scanning)
# -----------------------------------
async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=not DEBUG,
            args=["--window-size=1280,720", "--disable-blink-features=AutomationControlled"],
            channel="chrome"
        )
        
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        
        page = await context.new_page()
        
        # Continuous scanning loop
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
                            
                            # Skip if we've already visited this domain
                            if domain in visited_domains:
                                logger.info(f"⏩ Skipping already processed domain: {domain}")
                                continue
                                
                            visited_domains.add(domain)
                            base = f"{urlparse(res).scheme}://{domain}"
                            logger.info(f"🌐 Processing domain: {domain}")
                            
                            # Find and process contact pages
                            contact_pages = await find_contact_pages(page, base)
                            
                            if not contact_pages:
                                logger.info(f"No contact pages found for {domain}")
                                # Try common contact page as fallback
                                contact_url = urljoin(base, "/contact")
                                logger.info(f"🔄 Trying fallback contact page: {contact_url}")
                                contact_pages = [contact_url]
                            
                            for cp in contact_pages:
                                logger.info(f"📝 Attempting contact page: {cp}")
                                if await try_fill_form(page, cp):
                                    break
                                    
                            await asyncio.sleep(random.uniform(5, 15))
                        except Exception as e:
                            logger.error(f"Error processing {res}: {str(e)}")
                            continue
                except Exception as e:
                    logger.error(f"Search error for '{kw}': {str(e)}")
                    
            # Pause before next scan cycle
            wait_time = random.randint(45, 90)
            logger.info(f"🔄 Completed keyword cycle, restarting in {wait_time} seconds")
            await asyncio.sleep(wait_time)

if __name__ == "__main__":
    asyncio.run(main())
