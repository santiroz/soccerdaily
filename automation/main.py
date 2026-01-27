import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageEnhance
from groq import Groq, RateLimitError

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
except ImportError:
    print("⚠️ Google Indexing Libs not found. Install: pip install oauth2client google-api-python-client")

# --- CONFIGURATION ---
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://soccerdaily-alpha.vercel.app" 
INDEXNOW_KEY = "b3317ae5f84348fa8c96528a43ab2655" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# --- AUTHOR PROFILES (E-E-A-T STRATEGY) ---
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)",
    "Sarah Jenkins (Chief Editor)",
    "Luca Romano (Transfer Specialist)",
    "Marcus Reynolds (Premier League Correspondent)",
    "Elena Petrova (Tactical Expert)",
    "Hiroshi Tanaka (Data Scout)",
    "Ben Foster (Sports Journalist)"
]

# --- CATEGORY RSS FEED ---
CATEGORY_URLS = {
    "Transfer News": "https://news.google.com/rss/search?q=football+transfer+news+Fabrizio+Romano+here+we+go+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "Premier League": "https://news.google.com/rss/search?q=Premier+League+news+match+result+analysis+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "Champions League": "https://news.google.com/rss/search?q=UEFA+Champions+League+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "La Liga": "https://news.google.com/rss/search?q=La+Liga+Real+Madrid+Barcelona+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en"
}

# --- AUTHORITY SOURCES (OUTBOUND LINKS STRATEGY) ---
AUTHORITY_SOURCES = [
    "Transfermarkt", "Sky Sports", "The Athletic", "Opta Analyst",
    "WhoScored", "BBC Sport", "The Guardian", "UEFA Official", "ESPN FC"
]

# --- IMAGE DATABASE (STABILITY STRATEGY) ---
# Menggunakan Unsplash High Quality agar visual bagus dan tidak kena rate limit
SOCCER_IMAGES_DB = [
    "https://images.unsplash.com/photo-1522778119026-d647f0565c6a?auto=format&fit=crop&w=1200&q=80", 
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1579952363873-27f3bade9f55?auto=format&fit=crop&w=1200&q=80", 
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1574629810360-7efbbe195018?auto=format&fit=crop&w=1200&q=80", 
    "https://images.unsplash.com/photo-1624880357913-a8539238245b?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1560272564-c83b66b1ad12?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1518091043644-c1d4457512c6?auto=format&fit=crop&w=1200&q=80"
]

CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_CATEGORY = 1 

# --- MEMORY SYSTEM (INTERNAL LINKING STRATEGY) ---
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try: with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}/"
    if len(memory) > 50: memory = dict(list(memory.items())[-50:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_formatted_internal_links():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    if len(items) > 3: items = random.sample(items, 3)
    formatted_links = []
    for title, url in items:
        formatted_links.append(f"* [{title}]({url})")
    return "\n".join(formatted_links)

# --- RSS & SCRAPER (CONTENT DEPTH STRATEGY) ---
def fetch_rss_feed(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except: return None

def scrape_full_content(url):
    """
    Menggunakan Jina Reader agar bisa membaca FULL CONTENT berita.
    Ini kunci agar artikel tidak 'thin' dan terindeks Google.
    """
    jina_url = f"https://r.jina.ai/{url}"
    headers = {'User-Agent': 'Mozilla/5.0', 'X-No-Cache': 'true'}
    print(f"      🕵️ Reading via Jina AI: {url[:40]}...")
    try:
        response = requests.get(jina_url, headers=headers, timeout=25)
        if response.status_code == 200:
            text = response.text
            # Cleaning Data
            clean = re.sub(r'Images:.*', '', text, flags=re.DOTALL)
            clean = re.sub(r'\[.*?\]', '', clean)
            clean = re.sub(r'Title:.*', '', clean)
            clean = clean.strip()
            if len(clean) > 300: # Pastikan konten cukup panjang
                return clean[:8000]
    except: pass
    return None

# --- IMAGE ENGINE (ALT TEXT & STABILITY) ---
def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"): filename = filename.rsplit(".", 1)[0] + ".webp"
    
    # Gunakan Real Photo Database (Lebih SEO friendly & Trustworthy)
    selected_url = random.choice(SOCCER_IMAGES_DB)
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        response = requests.get(selected_url, headers=headers, timeout=15)
        if response.status_code == 200:
            img = Image.open(BytesIO(response.content)).convert("RGB")
            img = img.resize((1200, 675), Image.Resampling.LANCZOS)
            output_path = f"{IMAGE_DIR}/{filename}"
            img.save(output_path, "WEBP", quality=80)
            return f"/images/{filename}"
    except: pass
    return "/images/default.webp" # Fallback aman

# --- INDEXING ENGINE (TECHNICAL SEO) ---
def submit_to_indexnow(url):
    try:
        requests.post("https://api.indexnow.org/indexnow", json={
            "host": WEBSITE_URL.replace("https://", ""),
            "key": INDEXNOW_KEY,
            "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }, headers={'Content-Type': 'application/json'})
        print(f"      🚀 IndexNow Sent: {url}")
    except: pass

def submit_to_google(url):
    if not GOOGLE_JSON_KEY: return
    try:
        creds = json.loads(GOOGLE_JSON_KEY)
        service = build("indexing", "v3", credentials=ServiceAccountCredentials.from_json_keyfile_dict(creds, ["https://www.googleapis.com/auth/indexing"]))
        service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
        print(f"      🚀 Google Indexing Sent: {url}")
    except: pass

# --- AI WRITER (SCHEMA & STRUCTURE) ---
def get_groq_article_seo(title, source_text, internal_links_block, category, author_name):
    # Prompt ini mempertahankan struktur asli Anda (H2 Unik, Bullet Points, Data Table)
    # Serta memastikan Schema (Image Alt, LSI Keywords) terisi.
    
    selected_sources = ", ".join(random.sample(AUTHORITY_SOURCES, 3))
    
    system_prompt = f"""
    You are {author_name} for 'Soccer Daily'.
    TARGET CATEGORY: {category}
    
    GOAL: Write a 1000+ word article based on the SOURCE DATA.
    
    OUTPUT FORMAT (Strict JSON for Frontmatter Schema):
    {{
        "title": "Click-worthy Headline (Max 65 chars)",
        "description": "SEO Meta Description (155 chars)",
        "main_keyword": "Primary Subject",
        "lsi_keywords": ["keyword1", "keyword2", "keyword3"],
        "image_alt": "Descriptive Alt Text for SEO",
        "content": "Markdown Body"
    }}

    STRUCTURE REQ:
    1. **Executive Summary** (Hook the reader).
    2. **H2: The Breaking Story** (What happened - use details from source).
    3. **H2: Key Stats / Analysis** (Use Bullet points).
    4. **H2: Tactical Deep Dive** (Why it matters).
    5. **H2: Quotes & Reactions**.
    6. **H2: What's Next?**.
    
    MANDATORY:
    - Include this Internal Link block exactly as is near the bottom: \n{internal_links_block}
    - Mention these Authority Sources naturally: {selected_sources}.
    - NO AI words (Delve, Realm).
    """

    user_prompt = f"TOPIC: {title}\nSOURCE DATA: {source_text[:7500]}\n\nRespond with valid JSON."

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except: continue
    return None

# --- MAIN LOOP ---
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    for category_name, rss_url in CATEGORY_URLS.items():
        print(f"\n📡 Category: {category_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed or not feed.entries: continue

        count = 0
        for entry in feed.entries:
            if count >= TARGET_PER_CATEGORY: break

            clean_title = entry.title.split(" - ")[0]
            # Gunakan slug dari judul asli dulu untuk cek duplikasi
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            if os.path.exists(f"{CONTENT_DIR}/{slug}.md"): continue

            print(f"   🔥 Processing: {clean_title[:30]}...")

            # 1. SCRAPE FULL CONTENT (Agar tidak 'Thin Content')
            scraped_text = scrape_full_content(entry.link)
            source_data = scraped_text if scraped_text else entry.summary
            
            if len(source_data) < 100: 
                print("      ❌ Skipped: Content too short.")
                continue

            # 2. WRITE (Dengan Schema Lengkap)
            current_author = random.choice(AUTHOR_PROFILES)
            links_block = get_formatted_internal_links()
            
            json_str = get_groq_article_seo(clean_title, source_data, links_block, category_name, current_author)
            if not json_str: continue

            try:
                # Regex robust untuk ekstrak JSON
                match = re.search(r'\{.*\}', json_str, re.DOTALL)
                if match: data = json.loads(match.group(0))
                else: continue
            except: continue

            # Update Slug sesuai judul baru yang SEO Friendly
            final_slug = slugify(data['title'], max_length=60, word_boundary=True)
            filename = f"{final_slug}.md"

            # 3. IMAGE
            img_path = download_and_optimize_image(data.get('main_keyword', clean_title), f"{final_slug}.webp")
            
            # 4. SAVE (Frontmatter sesuai Schema Asli Anda)
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            tags_str = json.dumps(data.get('lsi_keywords', []))
            
            # FOOTER KHAS ANDA
            footer = f"\n\n---\n*Source: Analysis by {current_author} based on international reports and [Original Story]({entry.link}).*"

            md = f"""---
title: "{data['title']}"
date: {date_now}
author: "{current_author}"
categories: ["{category_name}"]
tags: {tags_str}
featured_image: "{img_path}"
featured_image_alt: "{data.get('image_alt', data['title'])}"
description: "{data['description']}"
slug: "{final_slug}"
draft: false
---

{data['content']}
{footer}
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f: f.write(md)
            save_link_to_memory(data['title'], final_slug)
            
            # 5. INDEXING
            full_url = f"{WEBSITE_URL}/{final_slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            
            print(f"   ✅ Published: {final_slug}")
            count += 1
            time.sleep(5)

if __name__ == "__main__":
    main()
