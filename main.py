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
ID_GUIDE_CHANNEL_ID = 1454803773527429121
DB_FILE = "users_db.json"
STREAM_URL = "https://www.twitch.tv/leux" 

# --- ÖZEL OYUN EŞLEŞTİRMELERİ ---
SPECIAL_GAMES = {
    "fivem": 218,
    "source sdk base 2007": 218,
    "source sdk": 218,
    "cs2": 730,
    "csgo": 730,
    "rust": 252490,
    "tf2": 440
}

# --- YARDIMCI FONKSİYONLAR ---
def load_db():
    if not os.path.exists(DB_FILE): return {"users": {}, "banned": []}
    with open(DB_FILE, "r", encoding="utf-8") as f: return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)

def format_duration_detailed(start_ts):
    if not start_ts: return "Hesaplanıyor..."
    seconds = int(time.time() - start_ts)
    if seconds < 0: seconds = 0
    
    months, seconds = divmod(seconds, 2592000)
    weeks, seconds = divmod(seconds, 604800)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    
    parts = []
    if months > 0: parts.append(f"{months} Ay")
    if weeks > 0: parts.append(f"{weeks} Hft")
    if days > 0: parts.append(f"{days} Gn")
    if hours > 0: parts.append(f"{hours} Sa")
    if minutes > 0: parts.append(f"{minutes} Dk")
    if seconds >= 0 or not parts: parts.append(f"{seconds} Sn")
    
    return ".".join(parts)

# active_sessions yapısı: { "discord_id": { "steam_user1": {process, last_msg}, "steam_user2": {...} } }
active_sessions = {}

# --- İŞLEM YÖNETİCİSİ ---
def monitor_output(user_id, steam_user, process):
    while True:
        try:
            line = process.stdout.readline()
            if not line: break
            clean_line = line.strip()
            # print(f"[WORKER-{steam_user}] {clean_line}") # Log kirliliği olmaması için kapalı

            if clean_line.startswith("{"):
                try:
                    data = json.loads(clean_line)
                    if data.get("type") == "STATUS":
                        if user_id in active_sessions and steam_user in active_sessions[user_id]:
                            active_sessions[user_id][steam_user]["last_msg"] = data["msg"]
                except: pass
        except: break

def start_steam_bot(user_id, username, password, game_ids):
    # game_ids burada sadece ID listesi olmalı
    if not os.path.exists("steam_worker.py"): return
    gids_str = ",".join(map(str, game_ids))
    cmd = [sys.executable, "-u", "steam_worker.py", str(user_id), username, password, gids_str]
    
    try:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
        
        if user_id not in active_sessions: active_sessions[user_id] = {}
        active_sessions[user_id][username] = {"process": process, "last_msg": "Bağlanıyor..."}
        
        threading.Thread(target=monitor_output, args=(str(user_id), username, process), daemon=True).start()
    except Exception as e: print(f"[HATA] {e}")

def send_command_to_worker(user_id, steam_user, command):
    if user_id in active_sessions and steam_user in active_sessions[user_id]:
        proc = active_sessions[user_id][steam_user]["process"]
        if proc.poll() is None:
            try: proc.stdin.write(command + "\n"); proc.stdin.flush(); return True
            except: pass
    return False

# --- ÇOKLU HESAP SEÇİM MENÜSÜ ---
class AccountSelectView(discord.ui.View):
    def __init__(self, accounts, callback_func):
        super().__init__(timeout=60)
        self.callback_func = callback_func
        
        options = []
        for acc in accounts:
            options.append(discord.SelectOption(label=acc, description="Bu hesabı seç", emoji="👤"))
            
        self.select = discord.ui.Select(placeholder="İşlem yapılacak Steam hesabını seçin...", min_values=1, max_values=1, options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        await self.callback_func(interaction, self.select.values[0])

# --- ID SAYFALAMA SİSTEMİ ---
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
        embed = discord.Embed(title=f"🔍 '{self.query}' Sonuçları", color=0x3498db)
        for item in current_items:
            embed.add_field(name=item['name'], value=f"ID: `{item['id']}`", inline=False)
        embed.set_footer(text=f"Sayfa {self.page + 1}/{self.max_pages + 1}")
        return embed

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.gray)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else: await interaction.response.defer()

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.max_pages:
            self.page += 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else: await interaction.response.defer()

# --- ARAYÜZ (LOGIN) ---
class CodeModal(discord.ui.Modal, title="🔐 Güvenlik Doğrulaması"):
    def __init__(self, user_id, steam_user):
        super().__init__()
        self.user_id = user_id
        self.steam_user = steam_user
    code = discord.ui.TextInput(label="Steam Guard Kodu", placeholder="Kodu buraya girin", max_length=10)
    async def on_submit(self, interaction: discord.Interaction):
        if send_command_to_worker(self.user_id, self.steam_user, f"CODE:{self.code.value}"):
            await interaction.response.send_message(f"✅ **{self.steam_user}** için kod iletildi.", ephemeral=True)
        else: await interaction.response.send_message("❌ Hata.", ephemeral=True)

class LoginCheckView(discord.ui.View):
    def __init__(self, user_id, steam_user):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.steam_user = steam_user
    @discord.ui.button(label="Güvenlik Kodu Gir", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def code_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CodeModal(self.user_id, self.steam_user))
    @discord.ui.button(label="Durumu Kontrol Et", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.user_id in active_sessions and self.steam_user in active_sessions[self.user_id]:
            st = active_sessions[self.user_id][self.steam_user]["last_msg"]
            if "KOD GEREKLİ" in st:
                await interaction.response.edit_message(embed=discord.Embed(title="⚠️ Kod Bekleniyor", description=f"Hesap: {self.steam_user}\n{st}", color=0xf1c40f), view=self)
            elif any(x in st.lower() for x in ["açıldı", "başarılı", "çalışıyor"]):
                await interaction.response.edit_message(content=f"✅ **{self.steam_user}** başarıyla giriş yaptı.", view=None)
            else: await interaction.response.edit_message(content=f"ℹ️ **{self.steam_user} Durum:** `{st}`", view=self)
        else: await interaction.response.edit_message(content="❌ Oturum kapalı.", view=None)

class LoginModal(discord.ui.Modal, title="☁️ Hesap Ekle / Başlat"):
    username = discord.ui.TextInput(label="Steam Kullanıcı Adı")
    password = discord.ui.TextInput(label="Şifre")
    game_ids = discord.ui.TextInput(label="Başlangıç Oyun ID'leri (Opsiyonel)", required=False, placeholder="730, 440")
    
    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id); db_int = load_db()
        if uid in db_int["banned"]: await interaction.response.send_message("⛔ Yasaklısınız.", ephemeral=True); return
        
        s_user = self.username.value
        s_pass = self.password.value
        
        # ID'leri parse et ve zaman damgasıyla kaydet
        raw_ids = [int(x.strip()) for x in self.game_ids.value.split(",") if x.strip().isdigit()] if self.game_ids.value else [730]
        games_dict = {str(gid): int(time.time()) for gid in raw_ids} # Her oyunun kendi başlama saati var

        if uid not in db_int["users"]: db_int["users"][uid] = {}
        
        # Mevcut hesabı güncelle veya yeni ekle
        db_int["users"][uid][s_user] = {
            "password": s_pass,
            "games": games_dict 
        }
        save_db(db_int)
        
        # Varsa eski process'i kapat
        if uid in active_sessions and s_user in active_sessions[uid]:
            try: active_sessions[uid][s_user]["process"].kill()
            except: pass
            
        start_steam_bot(uid, s_user, s_pass, list(games_dict.keys()))
        await interaction.response.send_message(f"🚀 **{s_user}** başlatılıyor...", view=LoginCheckView(uid, s_user), ephemeral=True)

class MainView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Bulut Oturumunu Başlat / Hesap Ekle", style=discord.ButtonStyle.success, emoji="☁️", custom_id="login")
    async def login(self, interaction: discord.Interaction, button: discord.ui.Button):
        try: await interaction.response.send_modal(LoginModal())
        except: pass

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
            db_c = load_db()
            total_acc = sum(len(accs) for accs in db_c.get("users", {}).values())
            
            active_games_count = 0
            for uid, user_sessions in active_sessions.items():
                for s_user, sess in user_sessions.items():
                    if sess.get("process") and sess["process"].poll() is None:
                        # DB'den oyun sayısını çek
                        user_games = db_c["users"].get(uid, {}).get(s_user, {}).get("games", {})
                        active_games_count += len(user_games)

            st_list = ["By Leux", f"👤 Hesap: {total_acc}", f"🎮 Aktif: {active_games_count}"]
            await self.change_presence(activity=discord.Streaming(name=st_list[self.status_index], url=STREAM_URL))
            self.status_index = (self.status_index + 1) % len(st_list)
        except: pass

bot = Bot()

# --- KOMUTLAR ---

# YARDIMCI: Hesap Seçimi veya Otomatik Seçim
async def get_target_account(interaction: discord.Interaction, callback):
    uid = str(interaction.user.id); db_i = load_db()
    if uid not in db_i["users"] or not db_i["users"][uid]:
        await interaction.response.send_message("❌ Hiçbir hesap ekli değil. Önce oturum açın.", ephemeral=True)
        return

    accounts = list(db_i["users"][uid].keys())
    if len(accounts) == 1:
        await callback(interaction, accounts[0])
    else:
        await interaction.response.send_message("❓ **Hangi hesap için işlem yapılsın?**", view=AccountSelectView(accounts, callback), ephemeral=True)

@bot.tree.command(name="idogren", description="Oyun ismini yazın, ID bulun.")
async def idogren(interaction: discord.Interaction, sorgu: str):
    s_clean = sorgu.lower().strip()
    if s_clean in SPECIAL_GAMES:
        await interaction.response.send_message(f"🎯 **Özel:** `{sorgu.upper()}` ID: `{SPECIAL_GAMES[s_clean]}`", ephemeral=True); return
    if "store.steampowered.com/app/" in sorgu:
        match = re.search(r"app/(\d+)", sorgu)
        if match: await interaction.response.send_message(f"🔍 ID: `{match.group(1)}`", ephemeral=True); return
    
    await interaction.response.defer(ephemeral=True)
    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={sorgu}&l=turkish&cc=TR"
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                d = await r.json()
                if d and d.get("items"):
                    await interaction.followup.send(embed=IDPaginationView(d["items"], sorgu).make_embed(), view=IDPaginationView(d["items"], sorgu), ephemeral=True)
                else: await interaction.followup.send("❌ Bulunamadı.", ephemeral=True)
    except: await interaction.followup.send("⚠️ Hata.", ephemeral=True)

@bot.tree.command(name="liste", description="Tüm hesaplarınızı ve oyun sürelerini gösterir.")
async def liste(interaction: discord.Interaction):
    if interaction.channel_id != CMD_CHANNEL_ID: return
    uid = str(interaction.user.id); db_i = load_db()
    
    if uid not in db_i["users"] or not db_i["users"][uid]:
        await interaction.response.send_message("❌ Ekli hesap yok.", ephemeral=True); return

    embed = discord.Embed(title="📊 Bulut Oturum Paneli", color=0xe91e63)
    
    for s_user, data in db_i["users"][uid].items():
        games_dict = data.get("games", {})
        
        status_txt = "🔴 Kapalı"
        if uid in active_sessions and s_user in active_sessions[uid]:
            proc = active_sessions[uid][s_user]["process"]
            if proc.poll() is None: status_txt = "🟢 Aktif"
        
        desc = "```ansi\n\u001b[1;36m ID      | DURUM  | SÜRE\u001b[0m\n"
        if games_dict:
            for gid, start_time in games_dict.items():
                t_str = format_duration_detailed(start_time) if status_txt == "🟢 Aktif" else "Durduruldu"
                desc += f" {str(gid).ljust(7)} | \u001b[1;32mAktif\u001b[0m  | {t_str}\n"
        else:
            desc += " OYUN YOK | -      | -\n"
        desc += "```"
        
        embed.add_field(name=f"👤 {s_user} ({status_txt})", value=desc, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="oyun_ekle", description="Seçilen hesaba oyun ekler.")
async def oyun_ekle(interaction: discord.Interaction, appid: int):
    async def _add(inter, s_user):
        uid = str(inter.user.id); db_i = load_db()
        games_dict = db_i["users"][uid][s_user].get("games", {})
        
        if str(appid) not in games_dict:
            # Oyunu ŞU ANKİ saat ile ekle
            games_dict[str(appid)] = int(time.time())
            db_i["users"][uid][s_user]["games"] = games_dict
            save_db(db_i)
            
            gids_list = list(games_dict.keys())
            send_command_to_worker(uid, s_user, f"UPDATE:{','.join(gids_list)}")
            
            msg = f"✅ **{appid}** eklendi (Hesap: {s_user})"
            if inter.response.is_done(): await inter.followup.send(msg, ephemeral=True)
            else: await inter.response.send_message(msg, ephemeral=True)
        else:
            msg = "⚠️ Bu oyun zaten listede."
            if inter.response.is_done(): await inter.followup.send(msg, ephemeral=True)
            else: await inter.response.send_message(msg, ephemeral=True)

    await get_target_account(interaction, _add)

@bot.tree.command(name="oyun_cikar", description="Seçilen hesaptan oyun siler.")
async def oyun_cikar(interaction: discord.Interaction, appid: int):
    async def _remove(inter, s_user):
        uid = str(inter.user.id); db_i = load_db()
        games_dict = db_i["users"][uid][s_user].get("games", {})
        
        if str(appid) in games_dict:
            del games_dict[str(appid)]
            db_i["users"][uid][s_user]["games"] = games_dict
            save_db(db_i)
            
            gids_list = list(games_dict.keys())
            cmd_str = ",".join(gids_list) if gids_list else "NONE"
            send_command_to_worker(uid, s_user, f"UPDATE:{cmd_str}")
            
            msg = f"🗑️ **{appid}** silindi (Hesap: {s_user})"
            if inter.response.is_done(): await inter.followup.send(msg, ephemeral=True)
            else: await inter.response.send_message(msg, ephemeral=True)
        else:
            msg = "⚠️ Bu oyun listede yok."
            if inter.response.is_done(): await inter.followup.send(msg, ephemeral=True)
            else: await inter.response.send_message(msg, ephemeral=True)

    await get_target_account(interaction, _remove)

@bot.tree.command(name="cikis", description="Seçilen hesabın oturumunu kapatır.")
async def cikis(interaction: discord.Interaction):
    async def _logout(inter, s_user):
        uid = str(inter.user.id)
        if uid in active_sessions and s_user in active_sessions[uid]:
            try: active_sessions[uid][s_user]["process"].kill()
            except: pass
            del active_sessions[uid][s_user]
            
            # Veritabanında oyun sürelerini sıfırla/silme işlemi opsiyonel, burada sadece process öldürüyoruz
            # Kullanıcı tekrar girerse süreleri sıfırlamak istiyorsanız LoginModal içinde zaten yapılıyor.
            
            msg = f"👋 **{s_user}** oturumu kapatıldı."
            if inter.response.is_done(): await inter.followup.send(msg, ephemeral=True)
            else: await inter.response.send_message(msg, ephemeral=True)
        else:
            msg = "❌ Bu hesap zaten aktif değil."
            if inter.response.is_done(): await inter.followup.send(msg, ephemeral=True)
            else: await inter.response.send_message(msg, ephemeral=True)

    await get_target_account(interaction, _logout)

@bot.event
async def on_ready():
    print(f"{bot.user} Hazır.")
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
    
    g_ch = bot.get_channel(ID_GUIDE_CHANNEL_ID)
    if g_ch:
        try:
            await g_ch.purge(limit=10)
            embed = discord.Embed(title="🔍 Oyun ID'sini Nasıl Öğrenirim?", color=0x3498db)
            embed.description = "Kasmak istediğiniz oyunun ID'sini öğrenmek için aşağıdaki komutu kullanabilirsiniz:\n\n👉 `/idogren (oyun ismi veya linki)`\n\n*Örn: rust, fivem, cs2*\n*Bot size özel olarak sayfa değiştirmeli şekilde yanıt verecektir.*"
            await g_ch.send(embed=embed)
        except: pass

if __name__ == "__main__": bot.run(TOKEN)
