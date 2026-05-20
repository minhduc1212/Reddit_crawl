import asyncio
import os
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def run():
    # Define the path for the user data directory
    user_data_dir = os.path.join(os.getcwd(), "reddit_user_data")
    
    # Wrap the async_playwright context manager with Stealth
    async with Stealth().use_async(async_playwright()) as p:
        # Launch persistent context
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        # Get the first page created by the persistent context
        pages = context.pages
        if pages:
            page = pages[0]
        else:
            page = await context.new_page()
        
        print("Navigating to Reddit...")
        await page.goto("https://www.reddit.com")
        
        print("Reddit loaded. You can now log in if needed. The session will be saved in 'reddit_user_data'.")
        
        # Keep the browser open for a while to allow interaction
        await asyncio.sleep(60)
        
        await context.close()

if __name__ == "__main__":
    asyncio.run(run())
