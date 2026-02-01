import os
import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from jinja2 import Template
import openai

# --- 設定 ---
# 環境変数または直接入力（セキュリティのため環境変数を推奨）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
openai.api_key = OPENAI_API_KEY

TEMPLATE_FILE = "index_template.html"
OUTPUT_FILE = "index.html"

async def fetch_nikkei_articles():
    """日経新聞から医療DX記事を取得"""
    articles = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # 医療DXでの検索結果ページ
        await page.goto("https://www.nikkei.com/search?keyword=%E5%8C%BB%E7%99%82DX")
        await page.wait_for_selector("article")
        
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        for item in soup.select("article")[:5]:
            title_tag = item.select_one("h3, a[title]")
            link_tag = item.find("a")
            if title_tag and link_tag:
                title = title_tag.get_text(strip=True)
                url = "https://www.nikkei.com" + link_tag['href'] if link_tag['href'].startswith("/") else link_tag['href']
                articles.append({"source": "日本経済新聞", "title": title, "url": url})
        
        await browser.close()
    return articles

async def fetch_prtimes_articles():
    """PR TIMESから医療AI記事を取得"""
    articles = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # 指定のカテゴリページ
        await page.goto("https://prtimes.jp/main/html/searchbiscate/busi_cate_id/025/lv2/47/")
        
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        # 「医療AI」に関連するものをフィルタリング
        found = 0
        for item in soup.select(".item"):
            title_tag = item.select_one(".title")
            link_tag = item.select_one("a.link")
            if title_tag and link_tag:
                title = title_tag.get_text(strip=True)
                if "AI" in title.upper() or "人工知能" in title:
                    url = "https://prtimes.jp" + link_tag['href']
                    articles.append({"source": "PR TIMES", "title": title, "url": url})
                    found += 1
            if found >= 5:
                break
        
        await browser.close()
    return articles

def summarize_article(title):
    """OpenAIを使用して3行要約を生成"""
    prompt = f"""
    以下のニュース記事のタイトルに基づき、編集者目線で3行（要点、背景、マーケターへの影響）に要約してください。
    各行を「・」で始めてください。
    
    記事タイトル: {title}
    """
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "あなたは優秀な医療IT専門の編集者です。"},
                      {"role": "user", "content": prompt}]
        )
        lines = response.choices[0].message.content.strip().split("\n")
        # 3行を抽出して整形
        summary = {
            "point": lines[0].replace("・要点：", "").replace("・", "").strip() if len(lines) > 0 else "要約中...",
            "background": lines[1].replace("・背景：", "").replace("・", "").strip() if len(lines) > 1 else "調査中...",
            "impact": lines[2].replace("・マーケターへの影響：", "").replace("・", "").strip() if len(lines) > 2 else "検討中..."
        }
        return summary
    except Exception as e:
        print(f"Error summarizing: {e}")
        return {"point": "取得エラー", "background": "APIキーを確認してください", "impact": "N/A"}

async def main():
    print("記事を取得中...")
    nikkei = await fetch_nikkei_articles()
    prtimes = await fetch_prtimes_articles()
    
    all_articles = nikkei + prtimes
    
    print("要約を生成中...")
    for art in all_articles:
        art["summary"] = summarize_article(art["title"])
    
    # HTMLテンプレートの読み込み
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template_str = f.read()
    
    template = Template(template_str)
    html_output = template.render(
        articles=all_articles,
        update_date=datetime.now().strftime("%Y.%m.%d")
    )
    
    # 結果の書き出し
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_output)
    
    print(f"更新完了: {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
