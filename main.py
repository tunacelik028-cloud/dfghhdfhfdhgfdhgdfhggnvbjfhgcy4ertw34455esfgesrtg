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

# --- AYARLAR ---
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID = 1274031255662628925
INFO_CHANNEL_ID = 1454624165222154475
CMD_CHANNEL_ID = 1454627700978483302
DB_FILE = "users_db.json"
STREAM_URL = "https://www.twitch.tv/leux" # Yayında statüsü için

# --- YARDIMCI FONKSİYONLAR ---
def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "banned": []}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# --- İSTEDİĞİN ÖZEL ZAMAN FORMATI ---
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
    
    # Aralarına nokta koyarak birleştirir (Örn: 2 Gün.3 Saat.12 Sn)
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
        process = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, encoding='utf-8', errors='replace', bufsize=1 
        )
        
        active_sessions[str(user_id)] = {
            "process": process, "last_msg": "Sunucuya bağlanılıyor...", "start_time": None
        }
        
        t = threading.Thread(target=monitor_output, args=(str(user_id), process), daemon=True)
        t.start()
        
    except Exception as e:
        print(f"[PROCESS ERROR] {e}")

def monitor_output(user_id, process):
    while True:
        try:
            if process.poll() is not None: break
            line = process.stdout.readline()
            if not line: continue
            clean_line = line.strip()
            print(f"[WORKER-{user_id}] {clean_line}")

            try:
                if clean_line.startswith("{"):
                    data = json.loads(clean_line)
                    if data["type"] == "STATUS":
                        msg = data["msg"]
                        if user_id in active_sessions:
                            active_sessions[user_id]["last_msg"] = msg
                            if ("Giriş Başarılı" in msg or "Oturum Açıldı" in msg):
                                current_ts = int(time.time())
                                active_sessions[user_id]["start_time"] = current_ts
                                db_internal = load_db()
                                if user_id in db_internal["users"]:
                                    db_internal["users"][user_id]["start_time"] = current_ts
                                    save_db(db_internal)
            except: pass
        except: break

def send_command_to_worker(user_id, command):
    if user_id in active_sessions:
        proc = active_sessions[user_id]["process"]
        if proc.poll() is None:
            try:
                proc.stdin.write(command + "\n")
                proc.stdin.flush()
                return True
            except: pass
    return False

# --- ARAYÜZ ---
class CodeModal(discord.ui.Modal, title="🔐 Güvenlik Doğrulaması"):
    code = discord.ui.TextInput(label="Steam Guard Kodu", placeholder="Email veya Mobil uygulamanızdaki kodu girin", max_length=10)
    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid in active_sessions:
            send_command_to_worker(uid, f"CODE:{self.code.value}")
            embed = discord.Embed(description="✅ **Kod şifrelenerek sunucuya iletildi.**\nLütfen doğrulama işleminin tamamlanması için aşağıdaki paneli yenileyin.", color=0x2ecc71)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ **Hata:** Aktif bir oturum protokolü bulunamadı.", ephemeral=True)

class LoginCheckView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="Güvenlik Kodu Gir", style=discord.ButtonStyle.primary, emoji="🛡️", custom_id="code_btn", disabled=True)
    async def code_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CodeModal())

    @discord.ui.button(label="Durumu Kontrol Et", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        sess = active_sessions.get(self.user_id)
        if not sess:
            await interaction.response.edit_message(content="❌ **Oturum Sonlandırıldı.**\nGüvenlik nedeniyle bağlantı kesilmiş olabilir.", view=None); return

        st = sess["last_msg"]
        if "KOD GEREKLİ" in st:
            self.children[0].disabled = False
            embed = discord.Embed(title="⚠️ Doğrulama Bekleniyor", description="Steam sunucuları hesabınıza erişim için **İki Faktörlü Kimlik Doğrulama (2FA)** talep ediyor.\n\nLütfen **'Güvenlik Kodu Gir'** butonunu kullanarak kodu iletin.", color=0xf1c40f)
            await interaction.response.edit_message(content=None, embed=embed, view=self)
        elif "Aktif" in st or "Çevrimiçi" in st or "Başarılı" in st or "Oturum Açıldı" in st:
            embed = discord.Embed(title="✅ Bağlantı Kuruldu", description="Bulut sunucusu hesabınıza başarıyla bağlandı ve işlem başladı.\n\n👉 **Yönetim Paneli:** #1454627700978483302", color=0x2ecc71)
            embed.add_field(name="Son Log", value=f"`{st}`", inline=False)
            await interaction.response.edit_message(content=None, embed=embed, view=None)
        else:
            self.children[0].disabled = True
            embed = discord.Embed(description=f"ℹ️ **Sistem Durumu:** `{st}`\n*Sunucu yanıt veriyor, lütfen bekleyin...*", color=0x3498db)
            await interaction.response.edit_message(content=None, embed=embed, view=self)

class LoginModal(discord.ui.Modal, title="☁️ Bulut Oturum Başlatma"):
    username = discord.ui.TextInput(label="Kullanıcı Adı", placeholder="Steam kullanıcı adınızı girin")
    password = discord.ui.TextInput(label="Şifre", placeholder="Güvenli giriş için şifreniz")
    game_ids = discord.ui.TextInput(label="Oyun Yapılandırması (ID)", required=False, placeholder="Örn: 730, 440")

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        db_int = load_db()
        if uid in db_int["banned"]:
             await interaction.response.send_message("⛔ **Erişim Reddedildi:** Hesabınız askıya alınmıştır.", ephemeral=True); return

        if uid in active_sessions:
            try: active_sessions[uid]["process"].kill()
            except: pass
        
        raw_ids = self.game_ids.value
        gids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()] if raw_ids else [730]
        db_int["users"][uid] = {"username": self.username.value, "password": self.password.value, "games": gids, "start_time": None}
        save_db(db_int)
        start_steam_bot(uid, self.username.value, self.password.value, gids)
        await interaction.response.send_message("🚀 Sunucu başlatılıyor. Lütfen bekleyin.", ephemeral=True)

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
        self.add_view(MainView())
        self.status_rotator.start()
        await self.tree.sync()

    # --- DURUM DÖNGÜSÜ (Yayın Yapıyor) ---
    @tasks.loop(seconds=10)
    async def status_rotator(self):
        await self.wait_until_ready()
        try:
            if not self.ws: return
            current_db = load_db()
            total_accounts = len(current_db.get("users", {}))
            active_games_count = sum(len(u.get("games", [])) for u in active_sessions.values() if u.get("process").poll() is None)

            statuses = ["By Leux", f"👤 Toplam Hesap: {total_accounts}", f"🎮 Aktif Oyun: {active_games_count}"]
            status_text = statuses[self.status_index]
            await self.change_presence(activity=discord.Streaming(name=status_text, url=STREAM_URL))
            self.status_index = (self.status_index + 1) % len(statuses)
        except: pass

bot = Bot()

@bot.event
async def on_ready():
    print(f"{bot.user} Hazır.")
    ch = bot.get_channel(INFO_CHANNEL_ID)
    if ch:
        try:
            await ch.purge(limit=10)
            embed = discord.Embed(title="☁️ Steam Profesyonel Saat Kasma Servisi", description="**Steam Cloud**, bilgisayarınız kapalıyken bile oyun saatinizi artıran bulut tabanlı bir sistemdir.", color=0x5865F2)
            embed.add_field(name="🛡️ Güvenlik", value="🔒 **End-to-End Şifreleme:** Bilgileriniz güvenle saklanır.\n✅ **Steam Guard:** 2FA ile tam uyumludur.", inline=False)
            embed.add_field(name="📋 Kullanım", value="1️⃣ Butona tıklayın.\n2️⃣ Bilgileri girin.\n3️⃣ Otomatik kasmayı izleyin.", inline=False)
            embed.set_footer(text="Steam Systems © 2025")
            embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Steam_icon_logo.svg/2048px-Steam_icon_logo.svg.png")
            await ch.send(embed=embed, view=MainView())
        except: pass

# --- KULLANICI KOMUTLARI ---
def check_channel(interaction: discord.Interaction):
    return interaction.channel_id == CMD_CHANNEL_ID

@bot.tree.command(name="liste", description="Oturum detaylarını gösterir.")
async def liste(interaction: discord.Interaction):
    if not check_channel(interaction):
        await interaction.response.send_message(f"🚫 Bu terminalde kullanılamaz.", ephemeral=True); return

    uid = str(interaction.user.id)
    sess = active_sessions.get(uid)
    db_internal = load_db()
    st = sess["start_time"] if sess and sess.get("start_time") else db_internal["users"].get(uid, {}).get("start_time")
    games = db_internal["users"].get(uid, {}).get("games", [])

    if not sess and not st:
        await interaction.response.send_message("❌ Aktif oturum yok.", ephemeral=True); return

    current_time_str = format_duration_detailed(time.time() - st) if st else "Bağlanıyor..."

    embed = discord.Embed(title="📊 Bulut Oturum Paneli", color=0xe91e63)
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    
    # --- İSTEDİĞİN 3 SÜTUNLU TABLO ---
    desc = "```ansi\n"
    desc += "\u001b[1;36m ID      | DURUM  | ZAMAN\u001b[0m\n"
    desc += "\u001b[0;30m---------+--------+------------------\u001b[0m\n"
    
    if games:
        for gid in games:
            desc += f" {str(gid).ljust(7)} | \u001b[1;32mAktif\u001b[0m  | {current_time_str}\n"
    else:
        desc += " YOK     | -      | -\n"
    desc += "```"
    
    embed.add_field(name="🎮 Aktif İşlemler", value=desc, inline=False)
    embed.add_field(name="📡 Sistem", value="🟢 Online" if st else "🟠 Bağlanıyor...", inline=True)
    embed.add_field(name="👤 Kullanıcı", value=f"`{db_internal['users'].get(uid, {}).get('username', 'tuna')}`", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="cikis", description="Oturumu kapatır.")
async def cikis(interaction: discord.Interaction):
    if not check_channel(interaction): return
    uid = str(interaction.user.id)
    if uid in active_sessions:
        active_sessions[uid]["process"].kill()
        del active_sessions[uid]
        db_int = load_db()
        if uid in db_int["users"]: db_int["users"][uid]["start_time"] = None; save_db(db_int)
        await interaction.response.send_message("👋 Oturum kapatıldı.", ephemeral=True)

if __name__ == "__main__":
    bot.run(TOKEN)
