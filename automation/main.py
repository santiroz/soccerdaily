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
from bs4 import BeautifulSoup 

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

# --- GOOGLE INDEXING LIBS ---
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build

# --- CONFIGURATION ---
# Pastikan Environment Variables sudah diset di Vercel/Local
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

# 🟢 CONFIGURASI DOMAIN
WEBSITE_URL = "https://soccerdaily-alpha.vercel.app" # Tanpa slash di akhir
INDEXNOW_KEY = "b3317ae5f84348fa8c96528a43ab2655" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# --- TIM PENULIS (NEWSROOM) ---
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
    "La Liga": "https://news.google.com/rss/search?q=La+Liga+Real+Madrid+Barcelona+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "Tactical Analysis": "https://news.google.com/rss/search?q=football+tactical+analysis+prediction+preview+when:1d&hl=en-GB&gl=GB&ceid=GB:en"
}

# --- FALLBACK IMAGES ---
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1556056504-5c7696c4c28d?auto=format&fit=crop&w=1200&q=80"
]

CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"

TARGET_PER_CATEGORY = 1 

# --- MEMORY SYSTEM (INTERNAL LINKING) ---
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}"
    # Simpan 50 link terakhir saja agar tidak terlalu besar
    if len(memory) > 50:
        memory = dict(list(memory.items())[-50:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_formatted_internal_links():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    # Ambil 3 link acak untuk variasi
    if len(items) > 3: items = random.sample(items, 3)
    formatted_links = []
    for title, url in items:
        formatted_links.append(f"* [{title}]({url})")
    return "\n".join(formatted_links)

# --- RSS FETCHER (ROBUST) ---
def fetch_rss_feed(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.google.com/'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200: return None
        return feedparser.parse(response.content)
    except: return None

# --- SCRAPER ENGINE (NEW & IMPORTANT) ---
def scrape_full_content(url):
    """
    Mengambil teks asli dari website sumber untuk menghindari konten kosong/placeholder.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    }
    try:
        print(f"      🕵️ Scraping detailed info: {url[:40]}...")
        response = requests.get(url, headers=headers, timeout=10)
        
        # Hanya proses jika sukses
        if response.status_code != 200: 
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Bersihkan elemen sampah (Iklan, Menu, Script)
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            element.decompose()
            
        # Ambil semua teks paragraf
        paragraphs = soup.find_all('p')
        text_content = " ".join([p.get_text() for p in paragraphs])
        
        # Bersihkan spasi ganda
        clean_text = re.sub(r'\s+', ' ', text_content).strip()
        
        # Jika hasil terlalu pendek (kurang dari 300 karakter), anggap gagal (mungkin diproteksi)
        if len(clean_text) < 300: 
            return None
            
        # Potong jika terlalu panjang (Max 8000 char untuk konteks AI)
        return clean_text[:8000] 
    except Exception as e:
        print(f"      ⚠️ Scraping error: {e}")
        return None

# --- IMAGE ENGINE (WEBP + ENHANCE) ---
def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"

    base_prompt = f"Professional sports photography of {query}, soccer match action, stadium atmosphere, 4k resolution, highly detailed, photorealistic, cinematic lighting, sharp focus"
    safe_prompt = base_prompt.replace(" ", "%20")[:250]
    
    print(f"      🎨 Generating HQ Image: {query[:30]}...")

    for attempt in range(2):
        seed = random.randint(1, 999999)
        image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1280&height=720&nologo=true&model=flux-realism&seed={seed}&enhance=true"
        
        try:
            response = requests.get(image_url, timeout=60)
            if response.status_code == 200 and "image" in response.headers.get("content-type", ""):
                img = Image.open(BytesIO(response.content)).convert("RGB")
                
                # Resize & Enhance
                img = img.resize((1200, 675), Image.Resampling.LANCZOS)
                enhancer = ImageEnhance.Sharpness(img)
                img = enhancer.enhance(1.3)
                
                output_path = f"{IMAGE_DIR}/{filename}"
                img.save(output_path, "WEBP", quality=80, method=6)
                return f"/images/{filename}" 
        except Exception:
            time.sleep(2)
    
    return random.choice(FALLBACK_IMAGES)

# --- INDEXING ENGINE (GOOGLE & INDEXNOW) ---
def submit_to_google(url):
    if not GOOGLE_JSON_KEY:
        print("      ⚠️ Google Indexing Skipped: No JSON Key.")
        return

    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        SCOPES = ["https://www.googleapis.com/auth/indexing"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
        service = build("indexing", "v3", credentials=credentials)

        body = {"url": url, "type": "URL_UPDATED"}
        service.urlNotifications().publish(body=body).execute()
        print(f"      🚀 Google Indexing Submitted: {url}")
    except Exception as e:
        print(f"      ⚠️ Google Indexing Error: {e}")

def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        
        data = {
            "host": host,
            "key": INDEXNOW_KEY,
            "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }
        
        headers = {'Content-Type': 'application/json; charset=utf-8'}
        requests.post(endpoint, json=data, headers=headers, timeout=10)
        print(f"      🚀 IndexNow Submitted: {url}")
    except Exception as e:
        print(f"      ⚠️ IndexNow Error: {e}")

# --- AI WRITER ENGINE (FIXED QUALITY) ---
def get_groq_article_seo(title, rss_summary, scraped_content, internal_links, category, author):
    # Logika Cerdas: Pilih source terbaik
    source_material = scraped_content if scraped_content else rss_summary
    source_type = "FULL ARTICLE TEXT" if scraped_content else "SHORT SUMMARY"
    
    # Prompt System yang diperketat
    system_prompt = f"""
    You are {author}, a senior journalist for 'Soccer Daily'.
    
    TASK: Write a comprehensive football news article based on the SOURCE MATERIAL provided.
    
    🚨 CRITICAL RULES (DO NOT IGNORE):
    1. **NO PLACEHOLDERS**: NEVER use brackets like [Player Name], [Date], or [Score]. If the specific name is missing in the source, use generic terms (e.g., "The striker", "The team") or rewrite the sentence.
    2. **FACTUAL**: Do not invent match scores or player quotes if they are not in the source.
    3. **ENGAGING**: Write for humans. No robotic intros like "In the dynamic realm of football...".
    
    OUTPUT FORMAT (Strict JSON):
    {{
        "title": "Engaging Headline (No Markdown)",
        "description": "SEO Meta Description (under 160 chars)",
        "main_keyword": "Primary Entity",
        "lsi_keywords": ["keyword1", "keyword2", "keyword3"],
        "content": "Full Article Body in Markdown"
    }}

    STRUCTURE REQ:
    - **H2: The Core News** (What actually happened)
    - **H2: Statistical/Tactical Context** (Why it matters)
    - **H2: Quotes & Reactions** (If available in source)
    - **Read More**: \n{internal_links}
    - **H2: Future Implications**
    """

    user_prompt = f"""
    TOPIC: {title}
    SOURCE TYPE: {source_type}
    SOURCE DATA:
    {source_material}
    
    Create the JSON response now.
    """

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({category}) using {source_type}...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.6, # Rendah agar faktual
                response_format={"type": "json_object"},
                max_tokens=6000
            )
            return completion.choices[0].message.content
        except RateLimitError:
            continue # Coba key berikutnya
        except Exception as e:
            print(f"      ⚠️ AI Error: {e}")
            return None
            
    return None

# --- MAIN LOOP ---
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    total_generated = 0

    for category_name, rss_url in CATEGORY_URLS.items():
        print(f"\n📡 Fetching Category: {category_name}...")
        feed = fetch_rss_feed(rss_url)
        if not feed or not feed.entries: continue

        cat_success_count = 0
        for entry in feed.entries:
            if cat_success_count >= TARGET_PER_CATEGORY: break

            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"

            # Cek jika file sudah ada
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue

            print(f"   🔥 Processing: {clean_title[:40]}...")

            # 1. SCRAPING (Langkah Kunci)
            scraped_text = scrape_full_content(entry.link)
            
            # QUALITY GATE: Jika scraping gagal & summary RSS terlalu pendek, SKIP.
            if not scraped_text and len(entry.summary) < 100:
                print("      ⚠️ Skipped: Source data too thin (Quality Control).")
                continue

            # 2. AI WRITING
            current_author = random.choice(AUTHOR_PROFILES)
            links_block = get_formatted_internal_links()
            
            json_str = get_groq_article_seo(clean_title, entry.summary, scraped_text, links_block, category_name, current_author)
            
            if not json_str: continue

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                print("      ⚠️ JSON Parsing Error. Skipping.")
                continue

            # 3. IMAGE GENERATION
            img_keyword = data.get('main_keyword', clean_title)
            img_name = f"{slug}.webp"
            final_img = download_and_optimize_image(img_keyword, img_name)
            
            # 4. SAVING FILE
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            tags = json.dumps(data.get('lsi_keywords', []))
            
            md_content = f"""---
title: "{data['title']}"
date: {date_now}
author: "{current_author}"
categories: ["{data.get('category', category_name)}"]
tags: {tags}
featured_image: "{final_img}"
description: "{data['description']}"
slug: "{slug}"
draft: false
---

{data['content']}
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f: f.write(md_content)
            
            # Simpan ke memori untuk internal linking artikel berikutnya
            save_link_to_memory(data['title'], slug)
            
            print(f"   ✅ Published: {filename}")
            cat_success_count += 1
            total_generated += 1
            
            # 5. INDEXING SUBMISSION (Dikembalikan)
            full_article_url = f"{WEBSITE_URL}/{slug}/"
            submit_to_indexnow(full_article_url)
            submit_to_google(full_article_url)
            
            time.sleep(5) # Jeda agar tidak dianggap bot spam

    print(f"\n🎉 DONE! Total Articles Created: {total_generated}")

if __name__ == "__main__":
    main()
