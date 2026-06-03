import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import time
from datetime import datetime
import json
import paho.mqtt.client as mqtt

# ==========================================
# 1. INISIALISASI FIREBASE
# ==========================================
# PERINGATAN: Pastikan credentials.json sudah masuk .gitignore!
cred = credentials.Certificate("credentials.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://smart-medicine-box-1e4e2-default-rtdb.firebaseio.com/'
})

ref_jadwal = db.reference('smart_medbox/jadwal')
ref_status = db.reference('smart_medbox/status')

daftar_jadwal = {}
status_alarm_aktif = False
jadwal_terakhir_terpicu = "" # Mencegah alarm terpicu berulang di menit yang sama

# ==========================================
# 2. KONFIGURASI MQTT (PAHO-MQTT)
# ==========================================
MQTT_BROKER = "broker.hivemq.com" # Menggunakan public broker untuk testing
MQTT_PORT = 1883
TOPIC_KIRIM = "medbox/backend/perintah"
TOPIC_TERIMA = "medbox/esp32/status"

def on_connect(client, userdata, flags, rc):
    print(f"🔌 [MQTT] Terhubung ke broker dengan kode status: {rc}")
    client.subscribe(TOPIC_TERIMA) # Mendengarkan balasan dari ESP32

def on_message(client, userdata, msg):
    global status_alarm_aktif
    
    payload = msg.payload.decode("utf-8")
    print(f"\n📥 [MQTT MASUK] Pesan dari ESP32: {payload}")
    
    try:
        data = json.loads(payload)
        # Jika ESP32 mengirim sinyal bahwa laci dibuka / obat diambil
        if data.get("status") == "OBAT_DIAMBIL":
            print("🧲 [SENSOR IOT] Laci obat terbuka! Obat terdeteksi diambil.")
            
            # Kasih tau web (Vue.js) kalau obat udah selesai diminum
            update_status_ke_vue(False, True, f"Obat sudah diminum tepat waktu.")
            
            # Kirim balik perintah ke ESP32 untuk mematikan sirine/indikator
            send_command_to_esp32("ALARM_OFF", {})
            
            status_alarm_aktif = False
            print("Sistem standby kembali. Menunggu jadwal selanjutnya...\n")
            
    except json.JSONDecodeError:
        print("❌ [MQTT ERROR] Format pesan tidak valid (harus berformat JSON)")

# Setup klien MQTT
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start() # Menjalankan listener MQTT di background thread

def send_command_to_esp32(command_type, data):
    """
    Mengirim perintah berformat JSON ke ESP32 via MQTT.
    """
    payload = json.dumps({"perintah": command_type, "data": data})
    mqtt_client.publish(TOPIC_KIRIM, payload)
    print(f"📤 [MQTT KELUAR] Topik: {TOPIC_KIRIM} | Payload: {payload}")

# ==========================================
# 3. REAL-TIME LISTENER (FIREBASE -> PYTHON)
# ==========================================
def listener_jadwal(event):
    global daftar_jadwal
    print("\n" + "="*50)
    print("🔔 [SINKRONISASI JADWAL FIREBASE] 🔔")
    
    if event.path == '/':
        if event.data:
            daftar_jadwal = event.data
            print(f"-> Berhasil memuat {len(daftar_jadwal)} jadwal obat.")
        else:
            daftar_jadwal = {}
    else:
        key = event.path.replace('/', '')
        if event.data:
            daftar_jadwal[key] = event.data
        else:
            if key in daftar_jadwal:
                del daftar_jadwal[key]
            
    send_command_to_esp32("SYNC_JADWAL", daftar_jadwal)
    print("="*50)

# ==========================================
# 4. UPDATE FIREBASE (PYTHON -> VUE.JS)
# ==========================================
def update_status_ke_vue(waktu_minum, sudah_diminum, pesan):
    try:
        ref_status.update({
            "waktu_minum_obat": waktu_minum,
            "obat_sudah_diminum": sudah_diminum,
            "pesan": pesan,
            "terakhir_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception as e:
        print(f"❌ [FIREBASE ERROR] Gagal update status: {e}")

# ==========================================
# 5. MESIN UTAMA (MAIN LOOP)
# ==========================================
print("⚙️  Menjalankan Mesin Backend Smart Medicine Box...")
ref_jadwal.listen(listener_jadwal)

update_status_ke_vue(False, False, "Sistem menyala & standby. Menunggu waktu obat...")

try:
    print("📡 Menjalankan sensor waktu, mengecek jadwal setiap detik...\n")
    
    while True:
        waktu_sekarang = datetime.now().strftime("%H:%M")
        ada_jadwal_sekarang = False
        obat_sekarang = ""
        
        for id_jadwal, data in daftar_jadwal.items():
            if not data: continue
            
            if data.get('is_active') and data.get('waktu') == waktu_sekarang:
                ada_jadwal_sekarang = True
                obat_sekarang = data.get('nama_obat', 'Obat')
                break
                
        # Trigger alarm HANYA JIKA belum aktif dan belum pernah terpicu di menit yang sama
        if ada_jadwal_sekarang and not status_alarm_aktif and waktu_sekarang != jadwal_terakhir_terpicu:
            status_alarm_aktif = True
            jadwal_terakhir_terpicu = waktu_sekarang
            pesan_alarm = f"Waktunya minum {obat_sekarang}!"
            
            print(f"\n⏰ [ALARM TRIGGERED] {pesan_alarm}")
            
            # 1. Kasih tau Vue.js
            update_status_ke_vue(True, False, pesan_alarm)
            
            # 2. Kasih tau ESP32 untuk buka laci & nyalakan DFPlayer
            send_command_to_esp32("ALARM_ON", {"obat": obat_sekarang})
            
            print("⏳ Menunggu pasien mengambil obat (menunggu MQTT dari ESP32)...")
            # Loop akan terus berputar normal di bawah, sementara MQTT on_message menunggu balasan

        time.sleep(1)

except KeyboardInterrupt:
    print("\n🔴 Program Backend dihentikan secara manual (Ctrl+C).")
    mqtt_client.loop_stop()