import asyncio
from playwright.async_api import async_playwright
import requests
import io
from datetime import datetime
from PIL import Image
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Telegram Configuration
BOT_TOKEN = "7619040891:AAF9pfQQme32XvhTfUb97jzky5w4ZEaBzwc"
CHAT_ID = "5172045930"

def send_to_telegram(image_bytes, caption):
    """Send screenshot to Telegram"""
    try:
        if not image_bytes or len(image_bytes) < 1024:
            logger.error("Invalid image for Telegram")
            return False
            
        img = Image.open(io.BytesIO(image_bytes))
        buf = io.BytesIO()
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
                logger.info("✅ Telegram: Message sent successfully")
                return True
            else:
                logger.error(f"❌ Telegram error: {r.status_code} - {r.text}")
                return False
    except Exception as e:
        logger.error(f"❌ Telegram send error: {e}")
        return False

async def test_adg_legal():
    """Test the bot with ADG Legal (no CAPTCHA)"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1350, 'height': 901},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        
        try:
            logger.info("🧪 TEST: Starting ADG Legal form test...")
            
            # Navigate directly to contact page
            await page.goto('https://adglegal.com/contact/', wait_until='networkidle')
            await page.wait_for_timeout(2000)
            
            # Wait for form
            await page.wait_for_selector('#contact-name', timeout=10000)
            
            # Fill form exactly as in your recording
            logger.info("📝 Filling form fields...")
            
            # Name
            await page.fill('#contact-name', 'Test User')
            await page.wait_for_timeout(500)
            
            # Email
            await page.fill('#contact-email', 'test@example.com')
            await page.wait_for_timeout(500)
            
            # Message
            await page.fill('#contact-message', 'Test message for bot verification')
            await page.wait_for_timeout(500)
            
            # Screenshot before submission
            form_screenshot = await page.screenshot(full_page=True)
            send_to_telegram(form_screenshot, "📝 FORM FILLED - ADG Legal\nReady to submit...")
            
            # SUBMIT FORM
            logger.info("✅ Clicking submit button...")
            await page.click('main button')  # Using your recorded selector
            await page.wait_for_timeout(5000)
            
            # Check for success
            success_text = await page.query_selector('text=Thank you for getting in touch')
            
            if success_text:
                logger.info("🎉 SUCCESS! Form submitted and thank you message detected!")
                success_screenshot = await page.screenshot(full_page=True)
                send_to_telegram(success_screenshot, "🎉 SUCCESS - ADG Legal Form Submitted!\nBot is working correctly! ✅")
                return True
            else:
                logger.warning("❓ No success message detected")
                current_screenshot = await page.screenshot(full_page=True)
                send_to_telegram(current_screenshot, "❓ Unknown result - ADG Legal\nNo thank you message detected")
                return False
                
        except Exception as e:
            logger.error(f"💥 TEST FAILED: {e}")
            try:
                error_screenshot = await page.screenshot(full_page=True)
                send_to_telegram(error_screenshot, f"💥 TEST FAILED - ADG Legal\nError: {str(e)}")
            except:
                pass
            return False
        finally:
            await browser.close()

async def main():
    """Run the test"""
    logger.info("🤖 STARTING BOT TEST...")
    success = await test_adg_legal()
    
    if success:
        logger.info("🎊 BOT TEST PASSED! Ready for improvements.")
    else:
        logger.info("🔧 BOT TEST FAILED! Needs debugging.")

if __name__ == "__main__":
    asyncio.run(main())
