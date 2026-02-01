import os
import json
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from jinja2 import Template
import openai

# --- 設定 ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
openai.api_key = OPENAI_API_KEY

TEMPLATE_FILE = "index_template.html"
ARCHIVE_DIR = "archive"
# GitHub Pages上で公開されるURLのベース（ユーザーの環境に合わせて調整）
BASE_URL = "https://yueru-2020.github.io/medical-dx-news"

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
                    if url.startswith("/"):
                        url = "https://www.nikkei.com" + url
                    articles.append({"source": "日本経済新聞", "title": title, "url": url})
        except Exception as e:
            print(f"Nikkei error: {e}")
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
                        if url.startswith("/"):
                            url = "https://prtimes.jp" + url
                        articles.append({"source": "PR TIMES", "title": title, "url": url})
                        found += 1
                if found >= 5:
                    break
        except Exception as e:
            print(f"PR TIMES error: {e}")
        await browser.close()
    return articles

def summarize_article(title):
    """OpenAIを使用して3行要約を生成"""
    prompt = f"以下の記事タイトルを編集者目線で3行（要点、背景、マーケターへの影響）に簡潔に要約して。各行『・』で始めて。\nタイトル: {title}"
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "医療IT専門の編集者です。"}, {"role": "user", "content": prompt}]
        )
        lines = response.choices[0].message.content.strip().split("\n")
        return {
            "point": lines[0].replace("・", "").strip() if len(lines) > 0 else "N/A",
            "background": lines[1].replace("・", "").strip() if len(lines) > 1 else "N/A",
            "impact": lines[2].replace("・", "").strip() if len(lines) > 2 else "N/A"
        }
    except:
        return {"point": "取得失敗", "background": "API利用枠またはキーを確認", "impact": "N/A"}

async def main():
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 記事取得
    nikkei = await fetch_nikkei_articles()
    prtimes = await fetch_prtimes_articles()
    all_articles = nikkei + prtimes
    
    for art in all_articles:
        art["summary"] = summarize_article(art["title"])
    
    # テンプレート読み込み
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = Template(f.read())
    
    # HTML生成（メイン）
    html_content = template.render(
        articles=all_articles,
        update_date=today_str,
        prev_date=yesterday,
        next_date=None # 最新ページに「次へ」は不要
    )
    
    # index.html (最新) として保存
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
        
    # アーカイブ用ファイルとしても保存 (例: archive/2026-02-01.html)
    archive_path = f"{ARCHIVE_DIR}/{today_str}.html"
    
    # アーカイブ用には「次へ」も必要かもしれないが、生成時点では翌日は未来なので
    # index.htmlと同じ内容で保存。過去分は翌日のスクリプト実行で「次へ」が繋がる運用になる。
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Update completed: index.html & {archive_path}")

if __name__ == "__main__":
    asyncio.run(main())
