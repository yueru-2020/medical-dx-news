import os
import json
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from jinja2 import Template
import openai
import feedparser

# --- 設定 ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

TEMPLATE_FILE = "index_template.html"
ARCHIVE_DIR = "archive"

if not os.path.exists(ARCHIVE_DIR):
    os.makedirs(ARCHIVE_DIR)

async def fetch_nikkei_articles():
    """日経新聞から医療DX記事を取得"""
    articles = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("https://www.nikkei.com/search?keyword=%E5%8C%BB%E7%99%82DX", timeout=60000)
            await page.wait_for_selector("article", timeout=10000)
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            for item in soup.select("article")[:5]:
                title_tag = item.select_one("h3, a[title]")
                link_tag = item.find("a")
                if title_tag and link_tag:
                    title = title_tag.get_text(strip=True)
                    url = link_tag['href']
                    if url.startswith("/"): url = "https://www.nikkei.com" + url
                    articles.append({"source": "日本経済新聞", "title": title, "url": url, "type": "news"})
        except Exception as e: print(f"Nikkei error: {e}")
        await browser.close()
    return articles

async def fetch_prtimes_articles():
    """PR TIMESから医療AI記事を取得"""
    articles = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("https://prtimes.jp/main/html/searchbiscate/busi_cate_id/025/lv2/47/", timeout=60000)
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            found = 0
            for item in soup.select(".item"):
                title_tag = item.select_one(".title")
                link_tag = item.select_one("a.link")
                if title_tag and link_tag:
                    title = title_tag.get_text(strip=True)
                    if "AI" in title.upper() or "人工知能" in title:
                        url = link_tag['href']
                        if url.startswith("/"): url = "https://prtimes.jp" + url
                        articles.append({"source": "PR TIMES", "title": title, "url": url, "type": "news"})
                        found += 1
                if found >= 5: break
        except Exception as e: print(f"PR TIMES error: {e}")
        await browser.close()
    return articles

async def fetch_journal_papers():
    """主要医学誌から最新論文を取得"""
    papers = []
    
    # 1. npj Digital Medicine (RSS)
    try:
        feed = feedparser.parse("https://www.nature.com/npjdigitalmed.rss")
        for entry in feed.entries[:2]:
            papers.append({"source": "npj Digital Medicine", "title": entry.title, "url": entry.link, "type": "paper"})
    except Exception as e: print(f"npj error: {e}")

    # 2. The Lancet Digital Health (RSS)
    try:
        feed = feedparser.parse("https://www.thelancet.com/rssfeed/landig_current.xml")
        for entry in feed.entries[:2]:
            papers.append({"source": "The Lancet Digital Health", "title": entry.title, "url": entry.link, "type": "paper"})
    except Exception as e: print(f"Lancet error: {e}")

    # 3. NEJM AI (Scraping because RSS 403s)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("https://ai.nejm.org/toc/nejmai/current", timeout=60000)
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            # Assuming standard Atypon structure for titles
            items = soup.select(".art-title a, .hlFld-Title a")
            found = 0
            for item in items:
                title = item.get_text(strip=True)
                url = item['href']
                if url.startswith("/"): url = "https://ai.nejm.org" + url
                if title and url:
                    papers.append({"source": "NEJM AI", "title": title, "url": url, "type": "paper"})
                    found += 1
                if found >= 2: break
        except Exception as e: print(f"NEJM AI error: {e}")
        await browser.close()
    
    return papers

def summarize_item(item):
    """OpenAIを使用して3行要約を生成 (最新のSDK形式)"""
    is_paper = item.get("type") == "paper"
    role_desc = "医療IT・デジタルヘルス専門の編集者" if not is_paper else "医学論文の解説に長けたサイエンスライター"
    
    prompt = f"""
    以下の{'論文タイトル' if is_paper else 'ニュースタイトル'}に基づき、編集者目線で3行（要点、背景、マーケターへの影響）に簡潔に要約してください。
    各行を「・」で始めてください。
    
    タイトル: {item['title']}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": f"あなたは優秀な{role_desc}です。"},
                      {"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content.strip()
        lines = content.split("\n")
        # 「・」を除去して整形
        return {
            "point": lines[0].replace("・", "").replace("要点：", "").strip() if len(lines) > 0 else "N/A",
            "background": lines[1].replace("・", "").replace("背景：", "").strip() if len(lines) > 1 else "N/A",
            "impact": lines[2].replace("・", "").replace("影響：", "").strip() if len(lines) > 2 else "N/A"
        }
    except Exception as e:
        print(f"Summary Error ({item['title'][:20]}...): {e}")
        return {"point": "要約生成失敗", "background": f"Error: {str(e)[:50]}", "impact": "N/A"}

async def main():
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    print("ニュースを取得中...")
    news_items = await fetch_nikkei_articles() + await fetch_prtimes_articles()
    
    print("論文を取得中...")
    paper_items = await fetch_journal_papers()
    
    all_items = news_items + paper_items
    
    print("要約を生成中...")
    for item in all_items:
        item["summary"] = summarize_item(item)
    
    # テンプレート読み込み
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = Template(f.read())
    
    # ニュースと論文を分けてテンプレートに渡す
    render_news = [i for i in all_items if i["type"] == "news"]
    render_papers = [i for i in all_items if i["type"] == "paper"]
    
    html_content = template.render(
        news_articles=render_news,
        paper_articles=render_papers,
        update_date=today_str,
        prev_date=yesterday
    )
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    with open(f"{ARCHIVE_DIR}/{today_str}.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    print("更新完了！")

if __name__ == "__main__":
    asyncio.run(main())
