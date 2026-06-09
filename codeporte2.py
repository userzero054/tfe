from machine import Pin, SoftSPI, PWM
from mfrc522 import MFRC522
from umqtt.simple import MQTTClient
import time
import network
import urequests

# ==========================================
# CONFIGURATION WI-FI, MQTT & PRTG
# ==========================================




def connecter_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connexion au Wi-Fi en cours...", end="")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        tentatives = 0
        while not wlan.isconnected() and tentatives < 20:
            time.sleep(0.5)
            print(".", end="")
            tentatives += 1
    if wlan.isconnected():
        print("\n[WI-FI] Connecte ! IP :", wlan.ifconfig()[0])
    else:
        print("\n[WI-FI] Echec de la connexion reseau.")

connecter_wifi()

def envoyer_alerte_prtg(statut_intrusion):
    if statut_intrusion:
        xml_data = "<prtg><result><channel>Securite Porte</channel><value>1</value></result><text> ALERTE : Porte forcee !</text><error>1</error></prtg>"
    else:
        xml_data = "<prtg><result><channel>Securite Porte</channel><value>0</value></result><text>Porte securisee</text><error>0</error></prtg>"
        
    try:
        reponse = urequests.post(PRTG_URL, data=xml_data)
        reponse.close()
        print("[PRTG] Statut mis a jour avec succes.")
    except Exception as e:
        print("[PRTG] Erreur d'envoi :", e)

# --- CALLBACK COMMANDES MQTT DU VPS POUR LA PORTE 2 ---
def callback_mqtt(topic, msg):
    try:
        cmd = msg.decode().strip()
    except Exception as e:
        print("Erreur decodage MQTT:", e)
        return

    print("📩 MQTT Recu:", cmd)
    if cmd == "OUVRIR": 
        sequence_ouverture("Commande distant App")

client.set_callback(callback_mqtt)

# ==========================================
# 1. CONFIGURATION DU SERVO MOTEUR
# ==========================================
servo = PWM(Pin(2), freq=50)

def fixer_angle(angle):
    nanosecondes = int(500000 + (angle / 180) * 1900000)
    servo.duty_ns(nanosecondes)

print("Initialisation du servo a 0° (Verrouille)...")
fixer_angle(0)

ouverture_autorisee = False
etat_alerte_en_cours = False

# ==========================================
# 2. CONFIGURATION DES COMPOSANTS DE SÉCURITÉ
# ==========================================
capteur_porte = Pin(4, Pin.IN, Pin.PULL_UP)
bouton_sortie = Pin(5, Pin.IN, Pin.PULL_UP)
buzzer = Pin(6, Pin.OUT, value=0)

def declencher_alarme(activer):
    if activer:
        buzzer.value(1)
    else:
        buzzer.value(0)

# ==========================================
# 3. CONFIGURATION DU LECTEUR RFID
# ==========================================
sck, mosi, miso = Pin(18), Pin(23), Pin(19)
spi = SoftSPI(baudrate=100000, polarity=0, phase=0, sck=sck, mosi=mosi, miso=miso)
lecteur = MFRC522(spi, 22, 21)

try:
    client.connect()
    client.subscribe(b"serrure/porte_2/commande")
    print("✅ MQTT PORTE 2 CONNECTE")
except Exception as e:
    print("❌ Erreur MQTT:", e)

print("Systeme complet operationnel et arme (PORTE 2) !")

def sequence_ouverture(source_nom):
    global ouverture_autorisee, etat_alerte_en_cours
    print("\n[ACCES ACCORDE] Declencheur : " + source_nom)
    
    declencher_alarme(False)
    if etat_alerte_en_cours:
        etat_alerte_en_cours = False
        envoyer_alerte_prtg(False)
    
    ouverture_autorisee = True
    print("Action : Deverrouillage mecanique (90°)...")
    fixer_angle(90)
    
    print("En attente de l'ouverture physique de la porte...")
    while capteur_porte.value() == 0:
        time.sleep(0.1)
        
    print("La porte est ouverte. En attente de fermeture complete...")
    while capteur_porte.value() == 1:
        time.sleep(0.1)
        
    print("Porte refermee detectee ! Verrouillage automatique...")
    time.sleep(0.5) 
    fixer_angle(0)
    
    ouverture_autorisee = False
    print("\nSysteme rearme et securise. Pret.")

# --- BOUCLE PRINCIPALE ---
try:
    while True:
        try:
            client.check_msg()
        except:
            pass

        wlan = network.WLAN(network.STA_IF)
        if not wlan.isconnected():
            connecter_wifi()

        if capteur_porte.value() == 1:
            if not ouverture_autorisee:
                if not etat_alerte_en_cours:
                    print("️ALERTE : PORTE FORCEE ")
                    declencher_alarme(True)
                    etat_alerte_en_cours = True
                    envoyer_alerte_prtg(True)
        else:
            if not ouverture_autorisee:
                if etat_alerte_en_cours:
                    print("️ Retour au calme : Porte recollee.")
                    declencher_alarme(False)
                    etat_alerte_en_cours = False
                    envoyer_alerte_prtg(False)
        
        if bouton_sortie.value() == 0:
            try:
                client.publish(b"serrure/porte_2/retour", b"BOUTON_SORTIE")
            except:
                pass
            sequence_ouverture("Bouton Poussoir Interieur")

        (stat, tag_type) = lecteur.request(0x26)
        if stat == 0: 
            (stat, uid) = lecteur.anticoll()
            if stat == 0:
                identifiant = "0x%02x%02x%02x%02x" % (uid[0], uid[1], uid[2], uid[3])
                print(f" Badge détecté : {identifiant}. Envoi au VPS...")
                try:
                    client.publish(b"serrure/porte_2/retour", f"SCAN_RFID:{identifiant}".encode())
                except:
                    pass
                time.sleep(2)
                
        time.sleep(0.05)

except KeyboardInterrupt:
    servo.deinit()
    declencher_alarme(False)
    print("\nSysteme arrete proprement.")
