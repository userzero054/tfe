import network, time, ntptime
from machine import Pin, SoftSPI, SoftI2C
from umqtt.simple import MQTTClient
from mfrc522 import MFRC522
from fingerprint import Fingerprint 
import SH1106

# --- CONFIG ---
ssid, password = "Rayan", "Raralerare12"
mqtt_server = "91.134.134.58"
client = MQTTClient("esp32_serrure", mqtt_server, user="esp32", password="181007")

# --- MATERIEL ---
relais = Pin(5, Pin.OUT, value=0)
bouton_int = Pin(4, Pin.IN, Pin.PULL_UP)
i2c = SoftI2C(scl=Pin(22), sda=Pin(21))
oled = SH1106.SH1106_I2C(128, 64, i2c, rotate=180)
oled.sleep(False)

spi = SoftSPI(baudrate=100000, sck=Pin(18), mosi=Pin(23), miso=Pin(19))
rfid = MFRC522(spi, 15, 2)
sensor = Fingerprint(tx_pin=3, rx_pin=20)

derniere_sec = -1
mode_actuel = "VEILLE" 
target_finger_id = 1  
timeout_mode = 0  

def ouvrir():
    relais.value(1)
    oled.fill(0); oled.text("OUVERTURE", 30, 25); oled.show()
    time.sleep(3)
    relais.value(0)

def bouton_sortie_declenche():
    relais.value(1)
    oled.fill(0); oled.text("BOUTON SORTIE", 15, 20); oled.text("OUVERTURE", 30, 40); oled.show()
    try: 
        client.publish(b"serrure/porte_1/retour", b"BOUTON_SORTIE")
    except: 
        pass
    time.sleep(3)
    relais.value(0)

# --- CALLBACK DES COMMANDES MQTT VENANT DU VPS ---
def callback_mqtt(topic, msg):
    global mode_actuel, target_finger_id, timeout_mode
    try:
        cmd = msg.decode().strip()
    except Exception as e:
        print("Erreur decodage MQTT:", e)
        return

    print("📩 MQTT:", cmd)
    
    if cmd == "OUVRIR": 
        ouvrir()
        
    elif cmd == "SCAN_NFC": 
        mode_actuel = "INSCR_NFC"
        timeout_mode = time.time() + 15 
        
    elif cmd.startswith("SCAN_FINGER:"): 
        target_finger_id = int(cmd.split(":")[1])
        mode_actuel = "INSCR_FINGER"
        timeout_mode = time.time() + 20 

    elif cmd.startswith("SUPPRIMER_SLOT:"):
        try:
            slot = int(cmd.split(":")[1])
            print(f"🗑️ Demande de suppression physique du slot: {slot}")
            
            slot_high = (slot >> 8) & 0xFF
            slot_low = slot & 0xFF
            
            # --- STRUCTURE UNIFIÉE DU PAQUET DE SUPPRESSION ---
            paquet_suppression = bytes([0x0c, slot_high, slot_low, 0x00, 0x01])
            sensor._send_packet(b'\x01', paquet_suppression) 
            
            reponse = sensor._get_reply()
            if reponse == 0x00:
                print(f"✅ Slot {slot} effacé physiquement avec succès.")
                oled.fill(0); oled.text("EMPREINTE SUPPR", 5, 25); oled.text(f"SLOT: {slot}", 35, 45); oled.show()
                client.publish(b"serrure/porte_1/retour", f"SLOT_DELETED:{slot}".encode())
                time.sleep(2)
            else:
                print(f"⚠️ Erreur capteur code: {hex(reponse)}")
                client.publish(b"serrure/porte_1/retour", f"SLOT_DELETE_ERROR:{slot}".encode())
        except Exception as err:
            print("❌ Erreur pendant l'exécution du START_DELETE:", err)

client.set_callback(callback_mqtt)

# --- LOGIQUE FINGERPRINT ---
def enroler_doigt_complet(slot):
    global timeout_mode
    oled.fill(0); oled.text("INSCRIPTION", 20, 10); oled.text("POSEZ DOIGT", 20, 35); oled.show()
    
    while True:
        if time.time() > timeout_mode: return "ERROR"
        sensor._send_packet(b'\x01', b'\x01')
        if sensor._get_reply() == 0x00:
            sensor._send_packet(b'\x01', b'\x02\x01')
            sensor._get_reply()
            break
        time.sleep(0.1)
    
    print("[ESP32] Vérification des doublons sur le capteur...")
    sensor._send_packet(b'\x01', b'\x04\x01\x00\x00\x00\xa6') 
    reply = sensor._get_reply()
    
    if reply == 0x00: 
        print(" [ESP32] Doublon physique détecté ")
        oled.fill(0); oled.text("EMPREINTE DEJA", 10, 20); oled.text("EXISTANTE !", 25, 40); oled.show()
        time.sleep(2)
        return "DOUBLON"
    
    print("[ESP32]  Nouvelle empreinte unique. Continuation de l'inscription...")
    
    oled.fill(0); oled.text("RETIREZ DOIGT", 15, 30); oled.show()
    time.sleep(2)
    
    oled.fill(0); oled.text("REPOSEZ DOIGT", 15, 30); oled.show()
    while True:
        if time.time() > timeout_mode: return "ERROR"
        sensor._send_packet(b'\x01', b'\x01')
        if sensor._get_reply() == 0x00:
            sensor._send_packet(b'\x01', b'\x02\x02')
            sensor._get_reply()
            break
        time.sleep(0.1)
    
    if sensor.store_model(slot):
        oled.fill(0); oled.text("SUCCES SLOT " + str(slot), 10, 30); oled.show(); time.sleep(1.5)
        return "SUCCESS"
        
    return "ERROR"

# --- CONNEXION WI-FI SÉCURISÉE (ÉVITE LE INTERNAL STATE ERROR) ---
w = network.WLAN(network.STA_IF)
w.active(False)  # Force la réinitialisation complète de l'interface sans fil
time.sleep(0.5)
w.active(True)
w.connect(ssid, password)

print("Connexion au Wi-Fi...", end="")
while not w.isconnected():
    time.sleep(0.5)
    print(".", end="")
print("\n✅ Wi-Fi connecté !")

try:
    client.connect()
    client.subscribe(b"serrure/porte_1/commande")
    ntptime.settime()
    print("✅ ESP32 PORTE 1 PRÊT ET ABONNÉ")
except Exception as e: 
    print("❌ Erreur de connexion MQTT:", e)

# --- BOUCLE PRINCIPALE ---
while True:
    try: 
        client.check_msg()
    except: 
        pass

    if bouton_int.value() == 0: 
        bouton_sortie_declenche()

    if mode_actuel != "VEILLE" and time.time() > timeout_mode:
        oled.fill(0); oled.text("ANNULATION", 25, 20); oled.text("TIMEOUT", 35, 40); oled.show()
        time.sleep(1.5)
        mode_actuel = "VEILLE"

    if mode_actuel == "INSCR_NFC":
        oled.fill(0); oled.text("MODE BADGE", 25, 10); oled.text("SCANNEZ...", 30, 35); oled.show()
        (stat, tag) = rfid.request(rfid.CARD_REQIDL)
        if stat == rfid.OK:
            (stat, uid) = rfid.anticoll()
            if stat == rfid.OK:
                val = "0x%02x%02x%02x%02x" % (uid[0], uid[1], uid[2], uid[3])
                client.publish(b"serrure/porte_1/retour", ("CHECK_NFC:" + val).encode())
                mode_actuel = "VEILLE" 

    elif mode_actuel == "INSCR_FINGER":
        resultat = enroler_doigt_complet(target_finger_id)
        if resultat == "SUCCESS":
            client.publish(b"serrure/porte_1/retour", f"CHECK_FINGER:{target_finger_id}".encode())
        elif resultat == "DOUBLON":
            client.publish(b"serrure/porte_1/retour", b"CHECK_FINGER:ERREUR_DOUBLON_PHYSIQUE")
        else:
            client.publish(b"serrure/porte_1/retour", b"CHECK_FINGER:ERROR")
        mode_actuel = "VEILLE"

    elif mode_actuel == "VEILLE":
        (stat, tag) = rfid.request(rfid.CARD_REQIDL)
        if stat == rfid.OK:
            (stat, uid) = rfid.anticoll()
            if stat == rfid.OK:
                nfc_val = "0x%02x%02x%02x%02x" % (uid[0], uid[1], uid[2], uid[3])
                oled.fill(0); oled.text("BADGE OK", 30, 20); oled.text("DOIGT ?", 40, 40); oled.show()
                
                start_wait = time.time()
                finger_found = -1
                
                while time.time() - start_wait < 8: 
                    sensor._send_packet(b'\x01', b'\x01')
                    if sensor._get_reply() == 0x00:
                        sensor._send_packet(b'\x01', b'\x02\x01')
                        sensor._get_reply()
                        sensor._send_packet(b'\x01', b'\x04\x01\x00\x01\x00\xa6')
                        time.sleep(0.15)
                        
                        if hasattr(sensor, 'uart') and sensor.uart is not None:
                            raw_reply = sensor.uart.read()
                            if raw_reply and len(raw_reply) >= 12 and raw_reply[9] == 0x00:
                                finger_found = (raw_reply[10] << 8) | raw_reply[11]
                        break
                    time.sleep(0.1)
                
                if finger_found != -1:
                    print(f"📡 SLOT IDENTIFIE : {finger_found}")
                    client.publish(b"serrure/porte_1/retour", f"ACCES_AUTH:{nfc_val}:{finger_found}".encode())
                else:
                    print("📡 Empreinte non reconnue.")
                    oled.fill(0); oled.text("ERREUR DOIGT", 15, 30); oled.show(); time.sleep(1)

        t = time.localtime(time.time() + 7200)
        if t[5] != derniere_sec:
            oled.fill(0)
            oled.text("SYSTEME PRET", 20, 10)
            oled.text("{:02d}:{:02d}:{:02d}".format(t[3], t[4], t[5]), 35, 40)
            oled.show()
            derniere_sec = t[5]

    time.sleep(0.1)