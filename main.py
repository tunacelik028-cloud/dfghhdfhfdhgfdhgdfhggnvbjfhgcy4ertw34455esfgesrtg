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
    if not seconds: return "Hesaplanıyor..."
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
                            if db["users"][user_id]["start_time"] is None and ("Giriş Başarılı" in msg or "Oturum Açıldı" in msg):
                                db["users"][user_id]["start_time"] = int(time.time())
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

# --- PROFESYONEL ARAYÜZ (Discord UI) ---
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
    game_ids = discord.ui.TextInput(label="Oyun Yapılandırması (ID)", required=False, placeholder="Örn: 730, 440 (Boş = Otomatik CS2)")

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        
        if uid in db["banned"]:
             await interaction.response.send_message("⛔ **Erişim Reddedildi:** Hesabınız sistem yöneticisi tarafından askıya alınmıştır.", ephemeral=True); return

        if uid in active_sessions:
            try: active_sessions[uid]["process"].kill()
            except: pass
        
        raw_ids = self.game_ids.value
        gids = []
        if raw_ids:
            try: gids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
            except: pass
        if not gids: gids = [730]

        db["users"][uid] = {"username": self.username.value, "password": self.password.value, "games": gids, "start_time": None}
        save_db(db)
        
        start_steam_bot(uid, self.username.value, self.password.value, gids)
        
        embed = discord.Embed(title="🚀 Sunucu Başlatılıyor", description="İsteğiniz işleme alındı ve sanal sunucu (VPS) üzerinde oturumunuz hazırlanıyor.\n\nLütfen aşağıdaki panelden süreci takip edin.", color=0x9b59b6)
        await interaction.response.send_message(embed=embed, view=LoginCheckView(uid), ephemeral=True)

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

    # --- DURUM DÖNGÜSÜ (By Leux, Toplam Hesap, Aktif Oyun) ---
    @tasks.loop(seconds=10)
    async def status_rotator(self):
        total_accounts = len(db["users"])
        active_games = sum(len(u.get("games", [])) for u in active_sessions.values())
        
        statuses = [
            "By Leux",
            f"👤 Toplam Hesap: {total_accounts}",
            f"🎮 Aktif Oyun: {active_games}"
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
            await ch.purge(limit=10)
            embed = discord.Embed(title="☁️ Steam Profesyonel Saat Kasma Servisi", description="**Steam Cloud**, bilgisayarınız kapalıyken bile oyun saatinizi artıran otomasyon sistemidir.", color=0x5865F2)
            embed.add_field(name="🖥️ Sistem Mimarisi", value="Sistemimiz, 7/24 aktif kalan yüksek performanslı sunucular üzerinde çalışır. Siz uyurken, okuldayken veya işteyken hesabınız **Online** kalır.", inline=False)
            embed.add_field(name="🛡️ Güvenlik Protokolleri", value="🔒 **End-to-End Şifreleme:** Bilgileriniz şifrelenir.\n✅ **Steam Guard Desteği:** 2FA ile tam uyumludur.", inline=False)
            embed.add_field(name="📋 Kullanım Kılavuzu", value="1️⃣ **Oturum Aç:** Butona tıklayın.\n2️⃣ **Yapılandırma:** Bilgilerinizi girin.\n3️⃣ **Doğrulama:** Sorulursa, Steam Guard kodunuzu girin.", inline=False)
            embed.set_footer(text="Steam Systems © 2025")
            embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Steam_icon_logo.svg/2048px-Steam_icon_logo.svg.png")
            await ch.send(embed=embed, view=MainView())
        except: pass

# --- KULLANICI KOMUTLARI ---
def check_channel(interaction: discord.Interaction):
    return interaction.channel_id == CMD_CHANNEL_ID

@bot.tree.command(name="yardım", description="Sistem komutları hakkında bilgi verir.")
async def yardim(interaction: discord.Interaction):
    embed = discord.Embed(title="🛠️ Sistem Komutları", color=0x2b2d31)
    embed.add_field(name="👤 Kullanıcı Paneli", value="`/liste`, `/durum`, `/oyun_ekle`, `/oyun_cikar`, `/cikis`", inline=False)
    if interaction.user.id == ADMIN_ID:
        embed.add_field(name="🛡️ Yönetici Paneli", value="`/admin_ban`, `/admin_unban`, `/admin_oyun`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="liste", description="Oturum detaylarını gösterir.")
async def liste(interaction: discord.Interaction):
    if not check_channel(interaction): return
    uid = str(interaction.user.id)
    if uid not in active_sessions:
        await interaction.response.send_message("❌ Oturum bulunamadı.", ephemeral=True); return
    
    st = db["users"][uid].get("start_time")
    time_str = format_duration_detailed(time.time() - st) if st else "Hesaplanıyor..."
    
    embed = discord.Embed(title="📊 Oturum İstatistikleri", color=0xe91e63)
    embed.add_field(name="⏱️ Toplam Çalışma Süresi", value=f"> {time_str}", inline=False)
    embed.add_field(name="📡 Sunucu Durumu", value="🟢 Online" if st else "Bağlanıyor...", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="durum", description="Anlık logu gösterir.")
async def durum(interaction: discord.Interaction):
    if not check_channel(interaction): return
    uid = str(interaction.user.id)
    if uid not in active_sessions: await interaction.response.send_message("❌ Pasif.", ephemeral=True); return
    msg = active_sessions[uid]["last_msg"]
    await interaction.response.send_message(f"📝 **Log:** `{msg}`", ephemeral=True)

@bot.tree.command(name="oyun_ekle", description="Listeye oyun ekler.")
async def oyun_ekle(interaction: discord.Interaction, id: int):
    if not check_channel(interaction): return
    uid = str(interaction.user.id)
    if uid not in active_sessions: return
    current_games = db["users"][uid].get("games", [])
    if id not in current_games:
        current_games.append(id)
        db["users"][uid]["games"] = current_games; save_db(db)
        send_command_to_worker(uid, f"UPDATE:{','.join(map(str, current_games))}")
        await interaction.response.send_message(f"✅ **{id}** eklendi.", ephemeral=True)

@bot.tree.command(name="oyun_cikar", description="Oyun siler.")
async def oyun_cikar(interaction: discord.Interaction, id: int):
    if not check_channel(interaction): return
    uid = str(interaction.user.id)
    if uid not in active_sessions: return
    current_games = db["users"][uid].get("games", [])
    if id in current_games:
        current_games.remove(id)
        db["users"][uid]["games"] = current_games; save_db(db)
        send_command_to_worker(uid, f"UPDATE:{','.join(map(str, current_games))}")
        await interaction.response.send_message(f"🗑️ **{id}** silindi.", ephemeral=True)

@bot.tree.command(name="cikis", description="Oturumu kapatır.")
async def cikis(interaction: discord.Interaction):
    if not check_channel(interaction): return
    uid = str(interaction.user.id)
    if uid in active_sessions:
        active_sessions[uid]["process"].kill()
        del active_sessions[uid]
        db["users"][uid]["start_time"] = None; save_db(db)
        await interaction.response.send_message("👋 Oturum kapatıldı.", ephemeral=True)

# --- ADMIN KOMUTLARI ---
@bot.tree.command(name="admin_ban", description="(Admin) Banla")
async def admin_ban(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != ADMIN_ID: return
    uid = str(user.id)
    if uid not in db["banned"]:
        db["banned"].append(uid); save_db(db)
        if uid in active_sessions: active_sessions[uid]["process"].kill(); del active_sessions[uid]
        await interaction.response.send_message(f"🚫 {user.name} yasaklandı.", ephemeral=True)

@bot.tree.command(name="admin_unban", description="(Admin) Ban kaldır")
async def admin_unban(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != ADMIN_ID: return
    uid = str(user.id)
    if uid in db["banned"]:
        db["banned"].remove(uid); save_db(db)
        await interaction.response.send_message(f"✅ {user.name} banı açıldı.", ephemeral=True)

if __name__ == "__main__":
    bot.run(TOKEN)
