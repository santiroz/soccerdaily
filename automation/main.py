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
from PIL import Image, ImageEnhance, ImageOps
from groq import Groq, RateLimitError
from bs4 import BeautifulSoup 

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

# --- GOOGLE INDEXING LIBS ---
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build

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
    {"name": "Dave Harsya", "role": "Senior Analyst", "style": "Analytical, data-driven, uses statistics"},
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

# --- AUTHORITY SITES ---
AUTHORITY_SITES = [
    "https://www.transfermarkt.com", "https://www.skysports.com/football",
    "https://www.bbc.com/sport/football", "https://theathletic.com",
    "https://www.whoscored.com"
]

# --- FALLBACK IMAGES ---
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80"
]

CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_CATEGORY = 1 

# --- MEMORY SYSTEM ---
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

# --- RSS FETCHER (INI YANG SEBELUMNYA HILANG) ---
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

# --- SCRAPER ENGINE ---
def scrape_full_content(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    }
    try:
        print(f"      🕵️ Scraping source...")
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Bersihkan elemen sampah
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe", "ads"]):
            element.decompose()
            
        paragraphs = soup.find_all('p')
        text_content = " ".join([p.get_text() for p in paragraphs])
        clean_text = re.sub(r'\s+', ' ', text_content).strip()
        
        if len(clean_text) < 300: return None
        return clean_text[:8000] 
    except Exception as e:
        print(f"      ⚠️ Scraping error: {e}")
        return None

# --- IMAGE ENGINE ---
def download_and_optimize_image(query, filename):
    time.sleep(4) # Jeda untuk menghindari rate limit
    
    if not filename.endswith(".webp"): 
        filename = filename.rsplit(".", 1)[0] + ".webp"

    base_prompt = f"Professional sports photography of {query}, soccer match action, dynamic angle, stadium lights, 8k, photorealistic, cinematic lighting, sharp focus"
    safe_prompt = base_prompt.replace(" ", "%20")[:250]
    
    print(f"      🎨 Generating HQ Image: {query[:30]}...")

    for attempt in range(3):
        seed = random.randint(1, 999999)
        image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1280&height=720&nologo=true&model=flux-realism&seed={seed}&enhance=true"
        
        try:
            response = requests.get(image_url, timeout=45)
            
            if response.status_code == 200 and "image" in response.headers.get("content-type", ""):
                img = Image.open(BytesIO(response.content)).convert("RGB")
                img = img.resize((1200, 675), Image.Resampling.LANCZOS)
                img = ImageEnhance.Sharpness(img).enhance(1.3)
                img = ImageEnhance.Color(img).enhance(1.1)
                
                output_path = f"{IMAGE_DIR}/{filename}"
                img.save(output_path, "WEBP", quality=80, method=6)
                print(f"      📸 HQ Image Saved")
                return f"/images/{filename}" 

        except Exception as e:
            time.sleep(2)
    
    print("      ❌ Using Fallback Image.")
    return random.choice(FALLBACK_IMAGES)

# --- INDEXING ENGINE ---
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
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json'})
        print(f"      🚀 IndexNow Sent: {url}")
    except Exception as e:
        print(f"      ⚠️ IndexNow Error: {e}")

def submit_to_google(url):
    if not GOOGLE_JSON_KEY: 
        print("      ⚠️ Google Key missing.")
        return
    try:
        creds = json.loads(GOOGLE_JSON_KEY)
        SCOPES = ["https://www.googleapis.com/auth/indexing"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds, SCOPES)
        service = build("indexing", "v3", credentials=credentials)
        
        body = {"url": url, "type": "URL_UPDATED"}
        service.urlNotifications().publish(body=body).execute()
        print(f"      🚀 Google Indexing Sent: {url}")
    except Exception as e:
        print(f"      ⚠️ Google Indexing Error: {e}")

# --- AI WRITER ENGINE ---
def get_groq_article_seo(title, source_text, category, author_obj):
    banned_words = [
        "delve", "realm", "tapestry", "underscores", "testament", 
        "poised to", "landscape", "dynamic", "conclusion", 
        "moreover", "furthermore", "it is worth noting", "unveiled"
    ]
    
    system_prompt = f"""
    You are {author_obj['name']}, a {author_obj['role']} for 'Soccer Daily'.
    YOUR STYLE: {author_obj['style']}.
    
    GOAL: Rewrite the provided news into a UNIQUE, HUMAN-LIKE article based on the SOURCE MATERIAL.
    
    🚨 STRICT HUMANIZATION RULES:
    1. **NO AI PATTERNS**: Do NOT use these words: {", ".join(banned_words)}.
    2. **BURSTINESS**: Mix short, punchy sentences with longer descriptive ones. Avoid repetitive sentence structures.
    3. **OPINIONATED**: Don't just report. Add analysis, rhetorical questions, or emotional context like a real fan or expert.
    4. **NO PLACEHOLDERS**: Never use brackets like [Name] or [Date]. If info is missing in source, write around it.
    5. **NO GENERIC INTROS**: Start directly with the action or a strong hook. No "In the world of football..."
    
    OUTPUT FORMAT (JSON Only):
    {{
        "title": "Click-worthy Headline (Max 60 chars)",
        "description": "Engaging Meta Description (150 chars)",
        "main_keyword": "Main Subject",
        "lsi_keywords": ["keyword1", "keyword2"],
        "content": "Markdown Body"
    }}
    
    STRUCTURE REQ:
    - **H2: The Lede** (What happened, written excitingly)
    - **H2: The Analysis** (Why it matters, apply your specific STYLE)
    - **H2: Quotes & Context** (Based on source data)
    - **H2: What's Next**
    """

    user_prompt = f"""
    TOPIC: {title}
    RAW DATA: {source_text[:6500]}
    
    Write it now using your persona ({author_obj['name']}). Make it undetectable as AI.
    """

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.75,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            print("      ⚠️ Groq Rate Limit - Switching Key...")
            continue
        except Exception as e:
            print(f"      ⚠️ AI Error: {e}")
            continue
            
    return None

# --- MAIN LOOP ---
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    for category_name, rss_url in CATEGORY_URLS.items():
        print(f"\n📡 Category: {category_name}")
        # PANGGILAN FUNGSI YANG SEBELUMNYA ERROR
        feed = fetch_rss_feed(rss_url)
        
        if not feed or not feed.entries: 
            print("   ⚠️ No feed found.")
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
            scraped_text = scrape_full_content(entry.link)
            if not scraped_text or len(scraped_text) < 400:
                print("      ⚠️ Skipped: Content too short/thin.")
                continue
            
            # 2. WRITE
            selected_author = random.choice(AUTHORS)
            print(f"      ✍️ Writer: {selected_author['name']} ({selected_author['style']})")
            
            json_str = get_groq_article_seo(clean_title, scraped_text, category_name, selected_author)
            if not json_str: continue
            
            try: 
                data = json.loads(json_str)
            except: 
                print("      ⚠️ JSON Error. Skipping.")
                continue

            # 3. IMAGE
            img_keyword = data.get('main_keyword', clean_title)
            img_path = download_and_optimize_image(img_keyword, f"{slug}.webp")

            # 4. APPEND LINKS
            internal_links = get_internal_links_list()
            read_more_block = ""
            if internal_links:
                read_more_block = "\n\n### 📖 Read More\n" + "\n".join([f"- [{t}]({u})" for t, u in internal_links])
            
            random_auth = random.choice(AUTHORITY_SITES)
            sources_block = f"\n\n---\n*Sources: Report based on coverage from [Original Article]({entry.link}) and data from [Authority Reference]({random_auth}).*"

            final_content = data['content'] + read_more_block + sources_block

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
