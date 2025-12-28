import discord
from discord import app_commands
from discord.ext import commands, tasks
import subprocess
import threading
import json
import os
import time
import sys
import datetime
import random
import re
import aiohttp

# --- AYARLAR ---
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID = 1274031255662628925
INFO_CHANNEL_ID = 1454624165222154475
CMD_CHANNEL_ID = 1454627700978483302
ID_GUIDE_CHANNEL_ID = 1454803773527429121 # ID Öğrenme kanalı
DB_FILE = "users_db.json"
STREAM_URL = "https://www.twitch.tv/leux" 

# --- ÖZEL OYUN EŞLEŞTİRMELERİ ---
SPECIAL_GAMES = {
    "fivem": 218,
    "source sdk base 2007": 218,
    "source sdk": 218,
    "cs2": 730,
    "csgo": 730
}

# --- YARDIMCI FONKSİYONLAR ---
def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "banned": []}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def format_duration_detailed(seconds):
    if not seconds or seconds < 0: return "Bağlanıyor..."
    seconds = int(seconds)
    months, seconds = divmod(seconds, 2592000)
    weeks, seconds = divmod(seconds, 604800)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if months > 0: parts.append(f"{months} Ay")
    if weeks > 0: parts.append(f"{weeks} Hafta")
    if days > 0: parts.append(f"{days} Gün")
    if hours > 0: parts.append(f"{hours} Saat")
    if minutes > 0: parts.append(f"{minutes} Dk")
    if seconds >= 0 or not parts: parts.append(f"{seconds} Sn")
    return ".".join(parts)

db = load_db()
active_sessions = {}

# --- İŞLEM YÖNETİCİSİ ---
def start_steam_bot(user_id, username, password, game_ids):
    if not os.path.exists("steam_worker.py"):
        print("[KRİTİK HATA] Worker dosyası bulunamadı!")
        return
    gids_str = ",".join(map(str, game_ids))
    cmd = [sys.executable, "-u", "steam_worker.py", str(user_id), username, password, gids_str]
    try:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
        active_sessions[str(user_id)] = {"process": process, "last_msg": "Sunucuya bağlanılıyor...", "start_time": None}
        threading.Thread(target=monitor_output, args=(str(user_id), process), daemon=True).start()
    except Exception as e: print(f"[PROCESS ERROR] {e}")

def monitor_output(user_id, process):
    while True:
        try:
            line = process.stdout.readline()
            if not line: break
            clean_line = line.strip()
            onay_kelimeleri = ["başarılı", "açıldı", "çalışıyor", "aktif", "ok"]
            if any(k in clean_line.lower() for k in onay_kelimeleri):
                ts = int(time.time())
                if user_id in active_sessions: active_sessions[user_id]["start_time"] = ts
                db_int = load_db()
                if user_id in db_int["users"] and db_int["users"][user_id].get("start_time") is None:
                    db_int["users"][user_id]["start_time"] = ts
                    save_db(db_int)
            if clean_line.startswith("{"):
                try:
                    data = json.loads(clean_line)
                    if data.get("type") == "STATUS" and user_id in active_sessions:
                        active_sessions[user_id]["last_msg"] = data["msg"]
                except: pass
        except: break

def send_command_to_worker(user_id, command):
    if user_id in active_sessions:
        proc = active_sessions[user_id]["process"]
        if proc.poll() is None:
            try:
                proc.stdin.write(command + "\n"); proc.stdin.flush()
                return True
            except: pass
    return False

# --- SAYFALAMA SİSTEMİ (ID ÖĞREN İÇİN) ---
class IDPaginationView(discord.ui.View):
    def __init__(self, data, query):
        super().__init__(timeout=60)
        self.data = data
        self.query = query
        self.page = 0
        self.per_page = 5
        self.max_pages = (len(data) - 1) // self.per_page

    def make_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        current_items = self.data[start:end]
        
        embed = discord.Embed(title=f"🔍 '{self.query}' İçin Arama Sonuçları", color=0x3498db)
        for item in current_items:
            embed.add_field(name=item['name'], value=f"ID: `{item['id']}`", inline=False)
        
        embed.set_footer(text=f"Sayfa {self.page + 1}/{self.max_pages + 1} | ID'yi kopyalayıp /oyun_ekle ile kullanın.")
        return embed

    @discord.ui.button(label="⬅️ Geri", style=discord.ButtonStyle.gray)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="İleri ➡️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.max_pages:
            self.page += 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else:
            await interaction.response.defer()

# --- ARAYÜZ ---
class CodeModal(discord.ui.Modal, title="🔐 Güvenlik Doğrulaması"):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
    code = discord.ui.TextInput(label="Steam Guard Kodu", placeholder="Kodu buraya girin", max_length=10)
    async def on_submit(self, interaction: discord.Interaction):
        if send_command_to_worker(self.user_id, f"CODE:{self.code.value}"):
            await interaction.response.send_message("✅ **Kod şifrelenerek sunucuya iletildi.**\nLütfen doğrulama işlemi için paneli yenileyin.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ **Hata:** Aktif bir oturum bulunamadı.", ephemeral=True)

class LoginCheckView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id
    @discord.ui.button(label="Güvenlik Kodu Gir", style=discord.ButtonStyle.primary, emoji="🛡️", custom_id="code_btn", disabled=True)
    async def code_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CodeModal(self.user_id))
    @discord.ui.button(label="Durumu Kontrol Et", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        sess = active_sessions.get(self.user_id)
        if not sess: await interaction.response.edit_message(content="❌ **Oturum Sonlandırıldı.**", view=None); return
        st = sess["last_msg"]
        if "KOD GEREKLİ" in st:
            self.children[0].disabled = False
            await interaction.response.edit_message(embed=discord.Embed(title="⚠️ Doğrulama Bekleniyor", description=st, color=0xf1c40f), view=self)
        else: await interaction.response.edit_message(content=f"ℹ️ **Sistem Durumu:** `{st}`", view=self)

class LoginModal(discord.ui.Modal, title="☁️ Bulut Oturum Başlatma"):
    username = discord.ui.TextInput(label="Kullanıcı Adı", placeholder="Steam kullanıcı adınızı girin")
    password = discord.ui.TextInput(label="Şifre", placeholder="Güvenli giriş için şifreniz")
    game_ids = discord.ui.TextInput(label="Oyun Yapılandırması (ID)", required=False, placeholder="Örn: 730, 440")
    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id); db_int = load_db()
        if uid in db_int["banned"]: await interaction.response.send_message("⛔ **Erişim Reddedildi.**", ephemeral=True); return
        gids = [int(x.strip()) for x in self.game_ids.value.split(",") if x.strip().isdigit()] if self.game_ids.value else [730]
        db_int["users"][uid] = {"username": self.username.value, "password": self.password.value, "games": gids, "start_time": None}
        save_db(db_int); start_steam_bot(uid, self.username.value, self.password.value, gids)
        await interaction.response.send_message("🚀 **Sunucu Başlatılıyor...**", view=LoginCheckView(uid), ephemeral=True)

class MainView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Bulut Oturumunu Başlat", style=discord.ButtonStyle.success, emoji="☁️", custom_id="login")
    async def login(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LoginModal())

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
        self.status_index = 0
    async def setup_hook(self):
        self.add_view(MainView()); self.status_rotator.start(); await self.tree.sync()
    @tasks.loop(seconds=10)
    async def status_rotator(self):
        await self.wait_until_ready()
        try:
            db_c = load_db(); total = len(db_c.get("users", {})); act = sum(1 for u in active_sessions.values() if u.get("process").poll() is None)
            st_list = ["By Leux", f"👤 Toplam Hesap: {total}", f"🎮 Aktif Oyun: {act}"]
            await self.change_presence(activity=discord.Streaming(name=st_list[self.status_index], url=STREAM_URL))
            self.status_index = (self.status_index + 1) % len(st_list)
        except: pass

bot = Bot()

# --- TÜM KOMUTLAR ---
@bot.tree.command(name="idogren", description="Oyun ismini yazın, sonuçları listeleyelim.")
async def idogren(interaction: discord.Interaction, sorgu: str):
    s_clean = sorgu.lower().strip()
    
    # 1. ÖZEL DURUMLAR (FiveM vb.)
    if s_clean in SPECIAL_GAMES:
        await interaction.response.send_message(f"🎯 **Özel Tanımlama:** `{sorgu.upper()}` için gereken AppID: `{SPECIAL_GAMES[s_clean]}`", ephemeral=True)
        return

    # 2. LİNK KONTROLÜ
    if "store.steampowered.com/app/" in sorgu:
        match = re.search(r"app/(\d+)", sorgu)
        if match:
            await interaction.response.send_message(f"🔍 Linkten çıkarılan ID: `{match.group(1)}`", ephemeral=True)
            return

    # 3. STEAM ARAMA VE SAYFALAMA
    await interaction.response.defer(ephemeral=True)
    try:
        search_url = f"https://store.steampowered.com/api/storesearch/?term={sorgu}&l=turkish&cc=TR"
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url) as resp:
                data = await resp.json()
                if data and data.get("items"):
                    view = IDPaginationView(data["items"], sorgu)
                    await interaction.followup.send(embed=view.make_embed(), view=view, ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ '{sorgu}' bulunamadı. Lütfen tam adını deneyin.", ephemeral=True)
    except:
        await interaction.followup.send("⚠️ Hata oluştu.", ephemeral=True)

@bot.tree.command(name="liste", description="Oturum detaylarını ve istatistikleri gösterir.")
async def liste(interaction: discord.Interaction):
    if not check_channel(interaction): await interaction.response.send_message(f"🚫 Sadece <#{CMD_CHANNEL_ID}> kanalında çalışır.", ephemeral=True); return
    uid = str(interaction.user.id); sess = active_sessions.get(uid); db_i = load_db()
    st = sess["start_time"] if sess and sess.get("start_time") else db_i["users"].get(uid, {}).get("start_time")
    games = db_i["users"].get(uid, {}).get("games", [])
    if not sess and not st: await interaction.response.send_message("❌ Aktif oturum yok.", ephemeral=True); return
    t_str = format_duration_detailed(time.time() - st) if st else "Bağlanıyor..."
    desc = "```ansi\n\u001b[1;36m ID      | DURUM  | ZAMAN\u001b[0m\n\u001b[0;30m---------+--------+------------------\u001b[0m\n"
    for gid in games: desc += f" {str(gid).ljust(7)} | \u001b[1;32mAktif\u001b[0m  | {t_str}\n"
    desc += "```"
    embed = discord.Embed(title="📊 Bulut Oturum Paneli", color=0xe91e63)
    embed.add_field(name="🎮 Aktif İşlemler", value=desc, inline=False)
    embed.add_field(name="📡 Sistem", value="🟢 Online" if st else "🟠 Bağlanıyor...", inline=True)
    embed.add_field(name="👤 Kullanıcı", value=f"`{db_i['users'].get(uid, {}).get('username', 'Bilinmiyor')}`", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="oyun_ekle", description="Mevcut oturumunuza yeni bir oyun ekler.")
async def oyun_ekle(interaction: discord.Interaction, appid: int):
    uid = str(interaction.user.id); db_i = load_db()
    if uid not in db_i["users"]: await interaction.response.send_message("❌ Kayıt bulunamadı.", ephemeral=True); return
    if appid not in db_i["users"][uid]["games"]:
        db_i["users"][uid]["games"].append(appid); save_db(db_i)
        send_command_to_worker(uid, f"UPDATE:{','.join(map(str, db_i['users'][uid]['games']))}")
        await interaction.response.send_message(f"✅ **{appid}** başarıyla eklendi.", ephemeral=True)

@bot.tree.command(name="oyun_cikar", description="Listenizden oyun çıkartır.")
async def oyun_cikar(interaction: discord.Interaction, appid: int):
    uid = str(interaction.user.id); db_i = load_db()
    if uid in db_i["users"] and appid in db_i["users"][uid]["games"]:
        db_i["users"][uid]["games"].remove(appid); save_db(db_i)
        send_command_to_worker(uid, f"UPDATE:{','.join(map(str, db_i['users'][uid]['games']))}")
        await interaction.response.send_message(f"🗑️ **{appid}** başarıyla çıkarıldı.", ephemeral=True)

@bot.tree.command(name="durum", description="Anlık process durumunu gösterir.")
async def durum(interaction: discord.Interaction):
    uid = str(interaction.user.id); sess = active_sessions.get(uid)
    if not sess: await interaction.response.send_message("❌ Aktif değilsin.", ephemeral=True); return
    await interaction.response.send_message(embed=discord.Embed(description=f"📝 **Log:** `{sess['last_msg']}`", color=0x95a5a6), ephemeral=True)

@bot.tree.command(name="cikis", description="Oturumu kapatır.")
async def cikis(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if uid in active_sessions:
        active_sessions[uid]["process"].kill(); del active_sessions[uid]
        db_i = load_db(); db_i["users"][uid]["start_time"] = None; save_db(db_i)
        await interaction.response.send_message("👋 Oturum kapatıldı.", ephemeral=True)

def check_channel(interaction): return interaction.channel_id == CMD_CHANNEL_ID

@bot.event
async def on_ready():
    print(f"{bot.user} Hazır.")
    # Ana Bilgi Kanalı
    ch = bot.get_channel(INFO_CHANNEL_ID)
    if ch:
        try:
            await ch.purge(limit=10)
            embed = discord.Embed(title="☁️ Steam Profesyonel Saat Kasma Servisi", description="**Steam Cloud**, bilgisayarınız kapalıyken bile oyun saatinizi artıran bulut tabanlı bir otomasyon sistemidir.", color=0x5865F2)
            embed.add_field(name="🖥️ Sistem Mimarisi", value="Sistemimiz, 7/24 aktif kalan yüksek performanslı sunucular üzerinde çalışır. Siz uyurken hesabınız **Online** kalır.", inline=False)
            embed.add_field(name="🛡️ Güvenlik Protokolleri", value="🔒 **End-to-End Şifreleme:** Bilgileriniz güvenle saklanır.\n✅ **Steam Guard Desteği:** 2FA ile tam uyumludur.", inline=False)
            embed.add_field(name="📋 Kullanım Kılavuzu", value="1️⃣ **Oturum Aç:** Aşağıdaki butona tıklayın.\n2️⃣ **Yapılandırma:** Bilgilerinizi girin.\n3️⃣ **Doğrulama:** Sorulursa, Guard kodunuzu girin.", inline=False)
            embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Steam_icon_logo.svg/2048px-Steam_icon_logo.svg.png")
            await ch.send(embed=embed, view=MainView())
        except: pass
    
    # ID Öğrenme Kanalı
    g_ch = bot.get_channel(ID_GUIDE_CHANNEL_ID)
    if g_ch:
        try:
            await g_ch.purge(limit=10)
            embed = discord.Embed(title="🔍 Oyun ID'sini Nasıl Öğrenirim?", color=0x3498db)
            embed.description = "Kasmak istediğiniz oyunun ID'sini öğrenmek için aşağıdaki komutu kullanabilirsiniz:\n\n👉 `/idogren (oyun ismi veya linki)`\n\n*Örn: rust, fivem, cs2*\n*Bot size özel olarak sayfa değiştirmeli şekilde yanıt verecektir.*"
            await g_ch.send(embed=embed)
        except: pass

if __name__ == "__main__": bot.run(TOKEN)
