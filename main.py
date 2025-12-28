# --- main.py (GELİŞMİŞ DURUM VE HATA DÜZELTMELİ) ---
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

# --- AYARLAR ---
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID = 1274031255662628925
INFO_CHANNEL_ID = 1454624165222154475
CMD_CHANNEL_ID = 1454627700978483302
DB_FILE = "users_db.json"
STREAM_URL = "https://www.twitch.tv/leux" 

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
    if not seconds or seconds < 0: return "Hesaplanıyor..."
    seconds = int(seconds)
    months, seconds = divmod(seconds, 2592000)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    
    parts = []
    if months > 0: parts.append(f"**{months}** Ay")
    if days > 0: parts.append(f"**{days}** Gün")
    if hours > 0: parts.append(f"**{hours}** Saat")
    if minutes > 0: parts.append(f"**{minutes}** Dk")
    parts.append(f"**{seconds}** Sn")
    return ", ".join(parts)

db = load_db()
active_sessions = {}

# --- İŞLEM YÖNETİCİSİ ---
def start_steam_bot(user_id, username, password, game_ids):
    if not os.path.exists("steam_worker.py"):
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
                            # BURASI KRİTİK: Durumu anlık güncelle
                            if "Oturum açıldı" in msg or "başarılı" in msg.lower():
                                current_time = int(time.time())
                                active_sessions[user_id]["start_time"] = current_time
                                if user_id in db["users"]:
                                    db["users"][user_id]["start_time"] = current_time
                                    save_db(db)
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

# --- MODALS & VIEWS (Aynı Kalıyor) ---
class CodeModal(discord.ui.Modal, title="🔐 Güvenlik Doğrulaması"):
    code = discord.ui.TextInput(label="Steam Guard Kodu", placeholder="Kodu girin", max_length=10)
    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid in active_sessions:
            send_command_to_worker(uid, f"CODE:{self.code.value}")
            await interaction.response.send_message("✅ Kod iletildi. Paneli yenileyin.", ephemeral=True)

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
            await interaction.response.edit_message(content="❌ Oturum Sonlandırıldı.", view=None); return
        st = sess["last_msg"]
        if "KOD GEREKLİ" in st:
            self.children[0].disabled = False
            await interaction.response.edit_message(embed=discord.Embed(title="⚠️ Kod Bekleniyor", color=0xf1c40f), view=self)
        elif "başarılı" in st.lower() or "açıldı" in st.lower():
            await interaction.response.edit_message(content="✅ Bağlantı Kuruldu!", view=None)
        else:
            await interaction.response.edit_message(content=f"ℹ️ Durum: `{st}`", view=self)

class LoginModal(discord.ui.Modal, title="☁️ Bulut Oturum Başlatma"):
    username = discord.ui.TextInput(label="Kullanıcı Adı")
    password = discord.ui.TextInput(label="Şifre")
    game_ids = discord.ui.TextInput(label="Oyun ID (AppID)", required=False, placeholder="730")

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        raw_ids = self.game_ids.value
        gids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()] if raw_ids else [730]
        
        db["users"][uid] = {"username": self.username.value, "password": self.password.value, "games": gids, "start_time": None}
        save_db(db)
        start_steam_bot(uid, self.username.value, self.password.value, gids)
        await interaction.response.send_message("🚀 Başlatılıyor...", view=LoginCheckView(uid), ephemeral=True)

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

    # --- DİNAMİK DURUM DÖNGÜSÜ ---
    @tasks.loop(seconds=10)
    async def status_rotator(self):
        total_accounts = len(db["users"])
        total_games = sum(len(u.get("games", [])) for u in active_sessions.values() if u.get("process").poll() is None)
        
        statuses = [
            "By Leux",
            f"👤 Toplam Hesap: {total_accounts}",
            f"🎮 Aktif Oyun: {total_games}"
        ]
        
        status = statuses[self.status_index]
        await self.change_presence(activity=discord.Streaming(name=status, url=STREAM_URL))
        self.status_index = (self.status_index + 1) % len(statuses)

bot = Bot()

@bot.event
async def on_ready():
    print(f"{bot.user} Hazır.")
    ch = bot.get_channel(INFO_CHANNEL_ID)
    if ch:
        try:
            await ch.purge(limit=5)
            embed = discord.Embed(title="☁️ Steam Saat Kasma Servisi", color=0x5865F2)
            embed.add_field(name="📋 Kullanım", value="Aşağıdaki butona basıp bilgilerinizi girin.", inline=False)
            await ch.send(embed=embed, view=MainView())
        except: pass

@bot.tree.command(name="liste", description="Oturum istatistiklerini gösterir.")
async def liste(interaction: discord.Interaction):
    if interaction.channel_id != CMD_CHANNEL_ID: return
    uid = str(interaction.user.id)
    
    # Bellekteki canlı veriyi kontrol et
    sess = active_sessions.get(uid)
    st = sess["start_time"] if sess else db["users"].get(uid, {}).get("start_time")
    
    if not sess:
        await interaction.response.send_message("❌ Aktif oturum yok.", ephemeral=True); return

    passed = time.time() - st if st else 0
    time_str = format_duration_detailed(passed) if st else "Hesaplanıyor..."

    embed = discord.Embed(title="📊 Oturum İstatistikleri", color=0xe91e63)
    embed.add_field(name="⏱️ Çalışma Süresi", value=f"> {time_str}", inline=False)
    embed.add_field(name="📡 Durum", value="🟢 Online" if st else "🟠 Bağlanıyor...", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# (Diğer komutlar: durum, cikis, oyun_ekle vb. aynı mantıkla devam eder)

if __name__ == "__main__":
    bot.run(TOKEN)
