# --- steam_worker.py (NO WEBAPI / FORCE CM MODE) ---

import sys
import time
import json
import threading
import queue

from steam.client import SteamClient
from steam.enums import EResult
import gevent

sys.stdout.reconfigure(encoding="utf-8")

# --------------------------------------------------
def send_status(msg):
    try:
        print(json.dumps({"type": "STATUS", "msg": msg}), flush=True)
    except:
        pass

# --------------------------------------------------
cmd_queue = queue.Queue()
LATEST_AUTH_CODE = None

def stdin_listener():
    global LATEST_AUTH_CODE
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            if line.startswith("CODE:"):
                LATEST_AUTH_CODE = line.split(":", 1)[1]
            else:
                cmd_queue.put(line)
        except:
            break

# --------------------------------------------------
class ForceCMSteamClient(SteamClient):
    def _bootstrap_cm_list(self):
        # ❌ WebAPI YOK – direkt CM
        self.servers = [
            ("162.254.197.163", 27017),
            ("162.254.196.66", 27017),
            ("155.133.248.37", 27017),
            ("162.254.198.40", 27017),
            ("155.133.238.198", 27017),
        ]
        send_status("⚠️ WebAPI kapalı, manuel CM ile bağlanılıyor.")

    def _parse_message(self, message):
        try:
            return super()._parse_message(message)
        except Exception:
            return None

# --------------------------------------------------
def run_bot():
    if len(sys.argv) < 4:
        return

    discord_id = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]

    game_ids = []
    if len(sys.argv) > 4:
        try:
            game_ids = [int(x) for x in sys.argv[4].split(",") if x.isdigit()]
        except:
            pass

    send_status("🔄 Sunucuya bağlanılıyor...")

    client = ForceCMSteamClient()
    client.set_credential_location(f"steam_data_{discord_id}")

    threading.Thread(target=stdin_listener, daemon=True).start()

    @client.on("logged_on")
    def on_login():
        send_status("✅ Giriş başarılı.")

        base_game = game_ids[0] if game_ids else 730
        client.games_played([base_game])
        send_status(f"🎮 Aktif oyun: {base_game}")

        if len(game_ids) > 1:
            gevent.spawn_later(
                15,
                lambda: (
                    client.games_played(game_ids),
                    send_status(f"🎮 Oyunlar güncellendi: {game_ids}")
                )
            )

    def command_loop():
        while True:
            try:
                while not cmd_queue.empty():
                    raw = cmd_queue.get_nowait()
                    if raw.startswith("UPDATE:") and client.connected:
                        ids = [int(x) for x in raw.split(":", 1)[1].split(",") if x.isdigit()]
                        if ids:
                            client.games_played(ids)
                            send_status(f"🔄 Güncellendi: {ids}")
            except:
                pass
            gevent.sleep(1)

    gevent.spawn(command_loop)

    try:
        result = client.login(username, password)
    except Exception as e:
        send_status(f"❌ Bağlantı hatası: {e}")
        return

    if result == EResult.AccountLoginDeniedThrottle:
        send_status("⛔ Steam throttle (48). 1 saat bekleyin veya IP değiştirin.")
        return

    if result in (
        EResult.AccountLogonDenied,
        EResult.AccountLoginDeniedNeedTwoFactor,
        EResult.TwoFactorCodeMismatch
    ):
        code_type = "Email" if result == EResult.AccountLogonDenied else "Mobil"
        send_status(f"⚠️ KOD GEREKLİ: {code_type}")

        global LATEST_AUTH_CODE
        LATEST_AUTH_CODE = None

        auth_code = None
        for _ in range(180):
            if LATEST_AUTH_CODE:
                auth_code = LATEST_AUTH_CODE
                break
            gevent.sleep(1)

        if not auth_code:
            send_status("❌ Kod girilmedi.")
            return

        send_status("🔄 Kod doğrulanıyor...")

        if code_type == "Email":
            result = client.login(username, password, auth_code=auth_code)
        else:
            result = client.login(username, password, two_factor_code=auth_code)

    if result == EResult.OK:
        send_status("✅ Oturum açıldı, sistem çalışıyor.")
        client.run_forever()
    else:
        send_status(f"❌ Giriş başarısız: {result}")

# --------------------------------------------------
if __name__ == "__main__":
    run_bot()