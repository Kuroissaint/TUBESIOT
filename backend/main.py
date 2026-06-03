import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import paho.mqtt.client as mqtt
import json
import time

# ==========================================
# 1. INISIALISASI FIREBASE
# ==========================================
# Pastikan file credentials.json ada di folder yang sama
cred = credentials.Certificate("credentials.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'URL_FIREBASE_KAMU_DI_SINI' # Ganti dengan URL Realtime DB kamu
})

# ==========================================
# 2. KONFIGURASI MQTT
# ==========================================
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TOPIC_JADWAL = "medbox/backend/jadwal"  # Topik untuk mengirim jadwal ke ESP32
TOPIC_STATUS = "medbox/esp32/status"    # Topik untuk menerima laporan dari ESP32

# ==========================================
# 3. FUNGSI PENERIMA PESAN DARI ESP32
# ==========================================
def on_message(client, userdata, msg):
    if msg.topic == TOPIC_STATUS:
        payload = msg.payload.decode('utf-8')
        print(f"[MQTT] Pesan masuk dari ESP32: {payload}")
        
        try:
            data = json.loads(payload)
            # Jika ESP32 lapor obat sudah diambil, update status di Firebase
            if data.get("status") == "OBAT_DIAMBIL":
                slot = data.get("slot")
                
                # Update status riwayat di Firebase biar muncul di Web (Vue)
                ref = db.reference(f'medbox/riwayat/slot_{slot}')
                ref.update({
                    'status': 'Sudah Diminum',
                    'timestamp': time.time()
                })
                print(f"[FIREBASE] Status Slot {slot} diupdate menjadi 'Sudah Diminum'!")
        except Exception as e:
            print("Gagal memproses JSON dari ESP32:", e)

# Setup MQTT Client
mqtt_client = mqtt.Client("Backend_MedBox_001")
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Berlangganan (subscribe) ke topik laporan ESP32
mqtt_client.subscribe(TOPIC_STATUS)
mqtt_client.loop_start()

# ==========================================
# 4. FUNGSI KIRIM JADWAL KE ESP32
# ==========================================
def kirim_jadwal_ke_esp32(jam, menit, slot):
    data_jadwal = {
        "jam": int(jam),
        "menit": int(menit),
        "slot": int(slot)
    }
    payload = json.dumps(data_jadwal)
    mqtt_client.publish(TOPIC_JADWAL, payload)
    print(f"[MQTT] Jadwal dikirim ke ESP32: {payload}")

# ==========================================
# 5. LISTENER FIREBASE (DETEKSI JADWAL BARU DARI WEB)
# ==========================================
def listener_jadwal(event):
    # Fungsi ini otomatis jalan kalau ada jadwal obat baru yang diinput dari web Vue
    print("[FIREBASE] Mendeteksi perubahan jadwal...")
    
    if isinstance(event.data, dict):
        jam = event.data.get('jam')
        menit = event.data.get('menit')
        slot = event.data.get('slot')
        
        if jam is not None and menit is not None and slot is not None:
            kirim_jadwal_ke_esp32(jam, menit, slot)

# Memantau perubahan data pada path 'medbox/jadwal_aktif' di Firebase
db.reference('medbox/jadwal_aktif').listen(listener_jadwal)

# ==========================================
# MAIN LOOP
# ==========================================
print("Backend Python Berjalan...")
print("Menunggu perubahan jadwal dari Frontend atau laporan dari ESP32...")

try:
    while True:
        # Biarkan program tetap hidup
        time.sleep(1)
except KeyboardInterrupt:
    print("\nBackend dihentikan oleh user.")
    mqtt_client.loop_stop()
    mqtt_client.disconnect()