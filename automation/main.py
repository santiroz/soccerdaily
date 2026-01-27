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
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://soccerdaily-alpha.vercel.app" 
INDEXNOW_KEY = "b3317ae5f84348fa8c96528a43ab2655" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# --- AUTHOR PROFILES (WITH PERSONALITIES) ---
# Kita beri 'Soul' pada penulis agar gaya bahasanya beda-beda
AUTHORS = [
    {"name": "Dave Harsya", "role": "Senior Analyst", "style": "Analytical, data-driven, uses statistics"},
    {"name": "Sarah Jenkins", "role": "Chief Editor", "style": "Professional, formal, straight to the point"},
    {"name": "Luca Romano", "role": "Transfer Specialist", "style": "Excited, uses slang like 'Here we go', energetic"},
    {"name": "Ben Foster", "role": "Sports Journalist", "style": "Opinionated, controversial, critical"},
    {"name": "Elena Petrova", "role": "Tactical Expert", "style": "Deep dive, focuses on formations and strategy"}
]

CATEGORY_URLS = {
    "Transfer News": "https://news.google.com/rss/search?q=football+transfer+news+Fabrizio+Romano+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "Premier League": "https://news.google.com/rss/search?q=Premier+League+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "Champions League": "https://news.google.com/rss/search?q=UEFA+Champions+League+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "La Liga": "https://news.google.com/rss/search?q=La+Liga+Real+Madrid+Barcelona+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
}

AUTHORITY_SITES = [
    "https://www.transfermarkt.com", "https://www.skysports.com/football",
    "https://www.bbc.com/sport/football", "https://theathletic.com",
    "https://www.whoscored.com"
]

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
    try: with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}/"
    if len(memory) > 50: memory = dict(list(memory.items())[-50:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_internal_links_list():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return []
    if len(items) > 3: items = random.sample(items, 3)
    return items

# --- SCRAPER ENGINE ---
def scrape_full_content(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        print(f"      🕵️ Scraping source...")
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: return None
        soup = BeautifulSoup(response.content, 'html.parser')
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            element.decompose()
        paragraphs = soup.find_all('p')
        text_content = " ".join([p.get_text() for p in paragraphs])
        clean_text = re.sub(r'\s+', ' ', text_content).strip()
        if len(clean_text) < 300: return None
        return clean_text[:7500] 
    except: return None

# --- IMAGE ENGINE ---
def download_and_optimize_image(query, filename):
    time.sleep(3) 
    if not filename.endswith(".webp"): filename = filename.rsplit(".", 1)[0] + ".webp"
    
    # Prompt lebih artistik agar tidak terlihat generik
    base_prompt = f"Editorial sports photography, {query}, emotional soccer moment, depth of field, 4k, canon eos r5"
    safe_prompt = base_prompt.replace(" ", "%20")[:150]
    
    print(f"      🎨 Generating Image: {query[:20]}...")
    seed = random.randint(1, 999999)
    image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1280&height=720&nologo=true&model=flux&seed={seed}"
    
    try:
        response = requests.get(image_url, timeout=30)
        if response.status_code == 200 and "image" in response.headers.get("content-type", ""):
            img = Image.open(BytesIO(response.content)).convert("RGB")
            img = img.resize((1200, 675), Image.Resampling.LANCZOS)
            img = ImageEnhance.Sharpness(img).enhance(1.2)
            img.save(f"{IMAGE_DIR}/{filename}", "WEBP", quality=80)
            return f"/images/{filename}" 
    except: pass
    return random.choice(FALLBACK_IMAGES)

# --- INDEXING ---
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

# --- HUMANIZED AI WRITER (CORE UPDATE) ---
def get_groq_article_seo(title, source_text, category, author_obj):
    
    # DAFTAR KATA YANG HARAM (Sering dideteksi AI detector)
    banned_words = [
        "delve", "realm", "tapestry", "underscores", "testament", 
        "poised to", "landscape", "dynamic", "conclusion", 
        "moreover", "furthermore", "it is worth noting", "unveiled"
    ]
    
    system_prompt = f"""
    You are {author_obj['name']}, a {author_obj['role']} for 'Soccer Daily'.
    YOUR STYLE: {author_obj['style']}.
    
    GOAL: Rewrite the provided news into a UNIQUE, HUMAN-LIKE article.
    
    🚨 STRICT HUMANIZATION RULES:
    1. **NO AI PATTERNS**: Do NOT use these words: {", ".join(banned_words)}.
    2. **BURSTINESS**: Mix short, punchy sentences with longer descriptive ones. Avoid repetitive sentence structures.
    3. **OPINIONATED**: Don't just report. Add analysis, rhetorical questions, or emotional context like a real fan or expert.
    4. **NO PLACEHOLDERS**: Never use brackets like [Name]. If info is missing, write around it.
    5. **NO GENERIC INTROS**: Start directly with the action or a strong hook. No "In the world of football..."
    
    OUTPUT FORMAT (JSON Only):
    {{
        "title": "Click-worthy Headline (Max 60 chars)",
        "description": "Engaging Meta Description (150 chars)",
        "main_keyword": "Main Subject",
        "lsi_keywords": ["keyword1", "keyword2"],
        "content": "Markdown Body"
    }}
    
    STRUCTURE:
    - **H2: The Lede** (What happened, written excitingly)
    - **H2: The Analysis** (Why it matters, apply your specific STYLE)
    - **H2: What They Said** (Quotes if any, or general reactions)
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
                temperature=0.75, # Sedikit lebih tinggi untuk variasi/kreativitas
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
        if not feed: continue

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
            # Validasi ketat: Konten harus cukup panjang agar bisa di-rewrite dengan baik
            if not scraped_text or len(scraped_text) < 500:
                print("      ⚠️ Skipped: Content too short/thin.")
                continue
            
            # 2. WRITE WITH PERSONA
            # Pilih penulis acak untuk variasi gaya bahasa
            selected_author = random.choice(AUTHORS)
            print(f"      ✍️ Writer: {selected_author['name']} ({selected_author['style']})")
            
            json_str = get_groq_article_seo(clean_title, scraped_text, category_name, selected_author)
            if not json_str: continue
            try: data = json.loads(json_str)
            except: continue

            # 3. IMAGE
            img_path = download_and_optimize_image(data.get('main_keyword', clean_title), f"{slug}.webp")

            # 4. APPEND LINKS (Manual)
            internal_links = get_internal_links_list()
            read_more = "\n\n### 📖 Read More\n" + "\n".join([f"- [{t}]({u})" for t, u in internal_links]) if internal_links else ""
            
            # External links dengan teks anchor yang natural
            random_auth = random.choice(AUTHORITY_SITES)
            sources = f"\n\n---\n*Sources: Report based on coverage from [Original Article]({entry.link}) and data from [Authority Reference]({random_auth}).*"

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
