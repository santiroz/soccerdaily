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
    print("⚠️ Google Indexing libraries not found. Indexing will be skipped.")

# --- CONFIGURATION ---
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://soccerdaily-alpha.vercel.app" 
INDEXNOW_KEY = "b3317ae5f84348fa8c96528a43ab2655" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# --- AUTHOR PROFILES ---
AUTHORS = [
    {"name": "Dave Harsya", "role": "Senior Analyst", "style": "Analytical, focuses on long-term stats"},
    {"name": "Sarah Jenkins", "role": "Chief Editor", "style": "Professional, formal, straight to the point"},
    {"name": "Luca Romano", "role": "Transfer Specialist", "style": "Excited, uses slang like 'Here we go', energetic"},
    {"name": "Ben Foster", "role": "Sports Journalist", "style": "Opinionated, controversial, critical"},
    {"name": "Elena Petrova", "role": "Tactical Expert", "style": "Deep dive, focuses on formations and strategy"}
]

# --- RSS FEEDS ---
CATEGORY_URLS = {
    "Transfer News": "https://news.google.com/rss/search?q=football+transfer+news+Fabrizio+Romano+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "Premier League": "https://news.google.com/rss/search?q=Premier+League+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "Champions League": "https://news.google.com/rss/search?q=UEFA+Champions+League+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "La Liga": "https://news.google.com/rss/search?q=La+Liga+Real+Madrid+Barcelona+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
}

# --- DATABASE FOTO ASLI (ANTI RATE LIMIT) ---
# Menggunakan foto asli berkualitas tinggi dari Unsplash.
# Ini solusi permanen untuk masalah "Rate Limit Reached" pixel art.
SOCCER_IMAGES_DB = [
    "https://images.unsplash.com/photo-1522778119026-d647f0565c6a?auto=format&fit=crop&w=1200&q=80", 
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1579952363873-27f3bade9f55?auto=format&fit=crop&w=1200&q=80", 
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1574629810360-7efbbe195018?auto=format&fit=crop&w=1200&q=80", 
    "https://images.unsplash.com/photo-1624880357913-a8539238245b?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1560272564-c83b66b1ad12?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1518091043644-c1d4457512c6?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1489944440615-453fc2b6a9a9?auto=format&fit=crop&w=1200&q=80"
]

CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_CATEGORY = 1 

# --- HELPER FUNCTIONS ---

def fetch_rss_feed(url):
    """Mengambil RSS feed dengan header browser agar tidak diblokir Google."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return feedparser.parse(response.content)
        return None
    except Exception as e:
        print(f"      ⚠️ RSS Error: {e}")
        return None

def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}/"
    if len(memory) > 50: 
        memory = dict(list(memory.items())[-50:])
    with open(MEMORY_FILE, 'w') as f: 
        json.dump(memory, f, indent=2)

def get_internal_links_list():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return []
    if len(items) > 3: items = random.sample(items, 3)
    return items

# --- SCRAPER (JINA READER) ---
def scrape_with_jina(url):
    """Menggunakan Jina AI untuk bypass blokir situs berita."""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        'User-Agent': 'Mozilla/5.0', 
        'X-No-Cache': 'true'
    }
    
    print(f"      🕵️ Reading via Jina AI: {url[:40]}...")
    try:
        response = requests.get(jina_url, headers=headers, timeout=25)
        if response.status_code == 200:
            text = response.text
            # Bersihkan metadata Jina
            clean = re.sub(r'Images:.*', '', text, flags=re.DOTALL)
            clean = re.sub(r'\[.*?\]', '', clean)
            clean = re.sub(r'Title:.*', '', clean)
            clean = clean.strip()
            
            if len(clean) > 200:
                print("      ✅ Jina Read Success!")
                return clean[:8000] # Batas karakter untuk prompt AI
    except Exception as e:
        print(f"      ⚠️ Jina Error: {e}")
    return None

# --- IMAGE ENGINE (UNSPLASH FALLBACK) ---
def download_and_optimize_image(query, filename):
    """
    Mengunduh gambar dari Unsplash (Database) untuk menghindari Rate Limit AI.
    """
    if not filename.endswith(".webp"): 
        filename = filename.rsplit(".", 1)[0] + ".webp"
    
    # Pilih gambar acak dari database
    selected_url = random.choice(SOCCER_IMAGES_DB)
    print(f"      📸 Selecting Real Photo (Anti-Limit) for: {query[:20]}...")
    
    # Header wajib agar Unsplash tidak menolak request python
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }

    try:
        response = requests.get(selected_url, headers=headers, timeout=20)
        if response.status_code == 200:
            img = Image.open(BytesIO(response.content)).convert("RGB")
            # Resize ke standar web (16:9)
            img = img.resize((1200, 675), Image.Resampling.LANCZOS)
            
            # Simpan
            output_path = f"{IMAGE_DIR}/{filename}"
            img.save(output_path, "WEBP", quality=80)
            return f"/images/{filename}"
    except Exception as e:
        print(f"      ⚠️ Image Download Error: {e}")
    
    # Jika gagal total, return path salah satu gambar default (jika ada di local)
    # Atau return string kosong, tapi sebaiknya jangan biarkan kosong.
    return "/images/default.webp" # Pastikan Anda punya default.webp atau biarkan script lanjut

# --- INDEXING ENGINE ---
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
    except Exception as e:
        print(f"      ⚠️ Google Indexing Error: {e}")

# --- AI WRITER ENGINE ---
def get_groq_article_seo(title, source_text, category, author_obj):
    system_prompt = f"""
    You are {author_obj['name']}, a {author_obj['role']} for 'Soccer Daily'.
    STYLE: {author_obj['style']}.
    TASK: Write a news article based on the text provided.
    
    RULES:
    1. NO AI WORDS (delve, realm, tapestry, underscores).
    2. OPINIONATED & ANALYTICAL.
    3. NO PLACEHOLDERS.
    
    OUTPUT JSON FORMAT ONLY:
    {{
        "title": "Headline (Max 60 chars)",
        "description": "Meta Description (150 chars)",
        "main_keyword": "Main Subject",
        "lsi_keywords": ["keyword1"],
        "content": "Markdown Body"
    }}
    """
    
    user_prompt = f"TOPIC: {title}\nSOURCE: {source_text[:7500]}\n\nRespond with valid JSON only."

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
        except RateLimitError:
            print("      ⚠️ Groq Rate Limit. Next key...")
            continue
        except Exception as e:
            print(f"      ⚠️ Groq Error: {e}")
            continue
    return None

# --- MAIN LOOP ---
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    for category_name, rss_url in CATEGORY_URLS.items():
        print(f"\n📡 Category: {category_name}")
        feed = fetch_rss_feed(rss_url)
        
        if not feed or not feed.entries:
            print("   ⚠️ RSS Fetch Failed or Empty.")
            continue

        count = 0
        for entry in feed.entries:
            if count >= TARGET_PER_CATEGORY: break
            
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"
            
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue
            
            print(f"   🔥 Processing: {clean_title[:30]}...")
            
            # 1. SCRAPE
            scraped_text = scrape_with_jina(entry.link)
            source_data = scraped_text if scraped_text else entry.summary
            
            if len(source_data) < 50:
                print("      ❌ Skipped: Content too short.")
                continue

            # 2. WRITE
            selected_author = random.choice(AUTHORS)
            json_str = get_groq_article_seo(clean_title, source_data, category_name, selected_author)
            
            if not json_str: continue
            
            # JSON CLEANER (ROBUST REGEX METHOD)
            try:
                # Cari pola {...} untuk memastikan hanya JSON yang diambil
                match = re.search(r'\{.*\}', json_str, re.DOTALL)
                if match:
                    clean_json = match.group(0)
                    data = json.loads(clean_json)
                else:
                    raise ValueError("No JSON object found")
            except Exception as e:
                print(f"      ⚠️ JSON Parsing Failed: {e}")
                continue

            # 3. IMAGE
            img_path = download_and_optimize_image(data.get('main_keyword', clean_title), f"{slug}.webp")
            
            # 4. LINKS
            internal_links = get_internal_links_list()
            read_more = ""
            if internal_links:
                read_more = "\n\n### 📖 Read More\n" + "\n".join([f"- [{t}]({u})" for t, u in internal_links])
            
            sources = f"\n\n---\n*Sources: Analysis based on reports from [Original Story]({entry.link}).*"
            
            final_content = data['content'] + read_more + sources

            # 5. SAVE
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            md = f"""---
title: "{data['title']}"
date: {date_now}
author: "{selected_author['name']}"
categories: ["{category_name}"]
tags: {json.dumps(data.get('lsi_keywords', []))}
featured_image: "{img_path}"
description: "{data['description']}"
slug: "{slug}"
url: "/{slug}/"
draft: false
---

{final_content}
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f: f.write(md)
            save_link_to_memory(data['title'], slug)
            
            # 6. INDEXING
            full_url = f"{WEBSITE_URL}/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            
            print(f"   ✅ Published: {slug}")
            count += 1
            time.sleep(5)

if __name__ == "__main__":
    main()
