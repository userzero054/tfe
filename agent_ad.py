import paho.mqtt.client as mqtt
import subprocess
 
# --- CONFIGURATION ---

 
def update_ad_user(username, client):
    print(f" Vérification AD pour : {username}")
    # Commande PowerShell simple pour vérifier si l'utilisateur existe
    cmd = f'Get-ADUser -Identity "{username}"'
 
    try:
        # Exécution de la commande avec capture d'erreur
        result = subprocess.run(["powershell", "-Command", cmd], check=True, capture_output=True)
        print(f" Utilisateur {username} trouvé dans l'Active Directory !")
        # Renvoie "VALID" au VPS comme attendu
        client.publish(TOPIC_CONFIRM, f"VALID|{username}")
 
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('cp1252')
        if "ADIdentityNotFoundException" in error_msg or "Cannot find an object" in error_msg:
            print(f" ERREUR : Utilisateur '{username}' introuvable dans l'AD.")
            # Renvoie "NOTFOUND" au VPS comme attendu
            client.publish(TOPIC_CONFIRM, f"NOTFOUND|{username}")
        else:
            print(f" Erreur PowerShell : {error_msg}")
            client.publish(TOPIC_CONFIRM, f"ERROR|{username}")
 
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(" Connecté au VPS (MQTT)")
        client.subscribe(TOPIC_SYNC)
    else:
        print(f" Échec de connexion : {rc}")
 
def on_message(client, userdata, msg):
    payload = msg.payload.decode().strip()  # Supprime les espaces cachés reçus du VPS
    print(f" Message reçu du VPS : {payload}")
    try:
        username = payload.strip()  # Sécurité supplémentaire pour nettoyer le nom
        if username:
            update_ad_user(username, client)
    except Exception as e:
        print(f"Erreur de traitement : {e}")
 
# Initialisation pour Paho-MQTT 2.x (Compatible avec ton serveur)
client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_message = on_message
 
print("Agent AD prêt et en attente...")
client.connect(MQTT_BROKER, 1883, 60)
client.loop_forever()
 

