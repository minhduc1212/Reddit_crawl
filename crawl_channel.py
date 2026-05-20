import asyncio
import json
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright
from playwright_stealth import Stealth


async def _launch_browser():
    """Launch a stealth browser with persistent user data."""
    user_data_dir = os.path.join(os.getcwd(), "reddit_user_data")
    stealth_ctx = Stealth().use_async(async_playwright())
    p = await stealth_ctx.__aenter__()
    context = await p.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    pages = context.pages
    page = pages[0] if pages else await context.new_page()
    return stealth_ctx, p, context, page


async def crawl_post(post_url: str, save_to_file: bool = True) -> dict:
    """
    Crawl a single Reddit post and extract all available data.

    Args:
        post_url: Full URL to the Reddit post.
        save_to_file: If True, saves the result as a JSON file in crawled_posts/.

    Returns:
        A dict containing post title, author, content, time, link, score,
        upvote ratio, comment count, flair, and all top-level comments.
    """
    stealth_ctx, p, context, page = await _launch_browser()

    try:
        print(f"Navigating to post: {post_url}")
        await page.goto(post_url, wait_until="domcontentloaded")
        # Wait for the main post element to appear
        await page.wait_for_selector("shreddit-post", timeout=15000)
        # Give extra time for comments to load
        await asyncio.sleep(2)

        # ── Extract post metadata from <shreddit-post> attributes ──
        post_el = page.locator("shreddit-post").first
        post_data = await _extract_post_element(post_el, page)
        post_data["url"] = post_url

        # ── Extract comments ──
        print("Extracting comments...")
        comments = await _extract_comments(page)
        post_data["comments"] = comments
        post_data["crawled_at"] = datetime.now().isoformat()

        # ── Save to file ──
        if save_to_file:
            out_dir = os.path.join(os.getcwd(), "crawled_posts")
            os.makedirs(out_dir, exist_ok=True)
            # Build a filename from the post id or title
            safe_name = re.sub(r'[^\w\-]', '_', post_data.get("id", "post"))[:80]
            out_path = os.path.join(out_dir, f"{safe_name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(post_data, f, ensure_ascii=False, indent=2)
            print(f"Post data saved to: {out_path}")

        _print_post_summary(post_data)
        return post_data

    finally:
        await context.close()
        await p.stop()
        await asyncio.sleep(0.25)


async def crawl_channel_posts(subreddit_url: str, max_posts: int = 10, save_to_file: bool = True) -> list[dict]:
    """
    Crawl multiple posts from a subreddit/channel listing page.

    Args:
        subreddit_url: URL to the subreddit (e.g. https://www.reddit.com/r/40kLore/).
        max_posts: Maximum number of posts to crawl.
        save_to_file: If True, saves each post as a JSON file and a combined listing.

    Returns:
        A list of dicts, one per post.
    """
    stealth_ctx, p, context, page = await _launch_browser()

    try:
        print(f"Navigating to subreddit: {subreddit_url}")
        await page.goto(subreddit_url, wait_until="domcontentloaded")
        await page.wait_for_selector("shreddit-post", timeout=15000)
        await asyncio.sleep(2)

        # Scroll to load more posts if needed
        loaded = await page.locator("shreddit-post").count()
        scroll_attempts = 0
        while loaded < max_posts and scroll_attempts < 10:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)
            new_count = await page.locator("shreddit-post").count()
            if new_count == loaded:
                scroll_attempts += 1
            else:
                scroll_attempts = 0
            loaded = new_count

        post_elements = page.locator("shreddit-post")
        count = min(await post_elements.count(), max_posts)
        print(f"Found {count} posts to crawl.")

        results = []
        for i in range(count):
            el = post_elements.nth(i)
            try:
                post_data = await _extract_post_element(el, page)
                post_data["crawled_at"] = datetime.now().isoformat()
                results.append(post_data)
                print(f"  [{i+1}/{count}] {post_data.get('title', '(no title)')}")
            except Exception as e:
                print(f"  [{i+1}/{count}] Error extracting post: {e}")

        # ── Save results ──
        if save_to_file and results:
            out_dir = os.path.join(os.getcwd(), "crawled_posts")
            os.makedirs(out_dir, exist_ok=True)
            subreddit_name = re.search(r'/r/([^/]+)', subreddit_url)
            name = subreddit_name.group(1) if subreddit_name else "channel"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(out_dir, f"{name}_{timestamp}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"\nAll post data saved to: {out_path}")

        return results

    finally:
        await context.close()
        await p.stop()
        await asyncio.sleep(0.25)


# ─────────────────────── Internal helpers ───────────────────────


async def _extract_post_element(post_el, page) -> dict:
    """Extract metadata and content from a single <shreddit-post> element."""
    # Read attributes directly from the web component
    attrs_to_read = [
        "id", "post-title", "author", "subreddit-prefixed-name",
        "score", "comment-count", "created-timestamp",
        "post-type", "content-href", "permalink", "flair",
    ]

    data = {}
    for attr in attrs_to_read:
        val = await post_el.get_attribute(attr)
        if val is not None:
            # Normalize key names: "post-title" -> "title"
            key = attr.replace("post-", "").replace("subreddit-prefixed-", "subreddit_").replace("-", "_")
            data[key] = val

    # Build full URL from permalink if available
    permalink = data.get("permalink") or await post_el.get_attribute("permalink")
    if permalink and not permalink.startswith("http"):
        data["url"] = f"https://www.reddit.com{permalink}"
    elif permalink:
        data["url"] = permalink

    # Try to get post body text content
    body_text = await _try_get_text(post_el, '[slot="text-body"]')
    if not body_text:
        body_text = await _try_get_text(post_el, '[data-testid="post-content"]')
    if not body_text:
        body_text = await _try_get_text(post_el, "div.md")
    data["body"] = body_text or ""

    # Try to get media/link info
    media_link = await post_el.get_attribute("content-href")
    if media_link:
        data["content_link"] = media_link

    return data


async def _try_get_text(parent_locator, selector: str) -> str | None:
    """Try to get inner text from a child selector; return None on failure."""
    try:
        child = parent_locator.locator(selector).first
        if await child.count() > 0:
            return (await child.inner_text()).strip()
    except Exception:
        pass
    return None


async def _extract_comments(page, max_comments: int = 50) -> list[dict]:
    """Extract top-level comments from the current post page."""
    comments = []
    comment_els = page.locator("shreddit-comment")
    count = min(await comment_els.count(), max_comments)

    for i in range(count):
        el = comment_els.nth(i)
        try:
            comment = {}
            comment["author"] = await el.get_attribute("author") or ""
            comment["score"] = await el.get_attribute("score") or ""
            comment["depth"] = await el.get_attribute("depth") or "0"
            comment["id"] = await el.get_attribute("thingid") or await el.get_attribute("id") or ""

            # Get comment body text
            body = await _try_get_text(el, '[slot="comment"]')
            if not body:
                body = await _try_get_text(el, "div.md")
            if not body:
                body = await _try_get_text(el, "p")
            comment["body"] = body or ""

            # Get timestamp
            time_el = el.locator("time").first
            if await time_el.count() > 0:
                comment["time"] = await time_el.get_attribute("datetime") or ""
            else:
                comment["time"] = ""

            comments.append(comment)
        except Exception as e:
            comments.append({"error": str(e)})

    return comments


def _print_post_summary(post_data: dict):
    """Print a human-readable summary of the crawled post."""
    print("\n" + "=" * 60)
    print(f"  Title:    {post_data.get('title', 'N/A')}")
    print(f"  Author:   {post_data.get('author', 'N/A')}")
    print(f"  Score:    {post_data.get('score', 'N/A')}")
    print(f"  Comments: {post_data.get('comment_count', 'N/A')}")
    print(f"  Time:     {post_data.get('created_timestamp', 'N/A')}")
    print(f"  URL:      {post_data.get('url', 'N/A')}")
    body = post_data.get("body", "")
    if body:
        preview = body[:200] + ("..." if len(body) > 200 else "")
        print(f"  Body:     {preview}")
    num_comments = len(post_data.get("comments", []))
    print(f"  Crawled Comments: {num_comments}")
    print("=" * 60 + "\n")


# ─────────────────── Original channel browsing ───────────────────


async def run():
    """Original interactive function — opens a subreddit for manual browsing."""
    user_data_dir = os.path.join(os.getcwd(), "reddit_user_data")

    async with Stealth().use_async(async_playwright()) as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        print("Navigating to Reddit Community...")
        await page.goto("https://www.reddit.com/r/40kLore/")

        print("Reddit community loaded. You can now interact with the content. ")

        await asyncio.to_thread(input, "Press Enter to close the browser and save the session...")
        await context.close()
    
    await asyncio.sleep(0.25)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python crawl_channel.py <post_url>           — Crawl a single post")
        print("  python crawl_channel.py --channel <url> [n]  — Crawl n posts from a subreddit")
        print("  python crawl_channel.py --browse             — Interactive browsing (original)")
        sys.exit(0)

    if sys.argv[1] == "--browse":
        asyncio.run(run())
    elif sys.argv[1] == "--channel":
        url = sys.argv[2] if len(sys.argv) > 2 else "https://www.reddit.com/r/40kLore/"
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        asyncio.run(crawl_channel_posts(url, max_posts=n))
    else:
        asyncio.run(crawl_post(sys.argv[1]))
