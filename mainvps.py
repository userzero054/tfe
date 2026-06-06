import paho.mqtt.client as mqtt
from supabase import create_client
import time
import json

# --- CONFIGURATION ---
SUPABASE_URL = "https://eunmuwnfcfafcxxbezvr.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV1bm11d25mY2ZhZmN4eGJlenZyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxNTUwNzUsImV4cCI6MjA5MTczMTA3NX0.7K_IEw7XWf3sEHgwiD8nJTl8g6d2rvkRLLWOXsAf3jk"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

MQTT_BROKER = "91.134.134.58"
MQTT_USER, MQTT_PASS = "esp32", "181007"

# --- TABLE DE CORRESPONDANCE LOCALE (Évite de planter sur une table SQL inexistante) ---
MAPPING_PORTES = {
    "porte_1": 1,
    "porte_2": 2
}

TOPIC_RETOUR_DYNAMIC = "serrure/+/retour"
TOPIC_CONFIRM_AD = "serrure/ad_confirm"
TOPIC_SYNC_AD = "serrure/sync_ad"

def enregistrer_log(status, user_id, badge, methode, porte):
    try:
        supabase.table("logs_acces").insert({
            "statut": status,
            "id_user": user_id,
            "badge_scan": badge,
            "methode": methode,
            "porte": porte
        }).execute()
        print(f"📝 Log enregistré : {status} | User ID: {user_id} | Méthode: {methode} | Porte: {porte}")
    except Exception as e:
        print(f" Erreur lors de l'insertion du log : {e}")

# --- CALLBACKS MQTT ---
def on_connect(client, userdata, flags, rc):
    print(f"✅ Connecté au Broker MQTT avec le code de retour : {rc}")
    client.subscribe(TOPIC_RETOUR_DYNAMIC)
    client.subscribe(TOPIC_CONFIRM_AD)

def on_message(client, userdata, msg):
    payload = msg.payload.decode().strip()
    topic = msg.topic
    print(f"📩 [MQTT {topic}] Message reçu : {payload}")

    # Extraction du nom de la porte depuis le topic (ex: "serrure/porte_1/retour" -> "porte_1")
    parts_topic = topic.split("/")
    if len(parts_topic) < 3:
        return
    nom_porte_evenement = parts_topic[1]

    # Résolution de l'ID numérique de la porte via notre dictionnaire Python local
    if nom_porte_evenement in MAPPING_PORTES:
        id_porte_evenement = MAPPING_PORTES[nom_porte_evenement]
    else:
        print(f"⚠️ La porte '{nom_porte_evenement}' n'est pas configurée dans le dictionnaire MAPPING_PORTES.")
        return

    # 1. Double authentification (porte_1 : Badge + Empreinte)
    if nom_porte_evenement == "porte_1" and payload.startswith("ACCES_AUTH:"):
        try:
            parts = payload.split(":")
            badge_scanne = parts[1]
            finger_id_scanne = int(parts[2])

            res_user = supabase.table("utilisateurs").select("*").eq("nfc_id", badge_scanne).eq("fingerprint_id", finger_id_scanne).execute()
            
            if res_user.data:
                user = res_user.data[0]
                user_id = user['id']
                nom_user = user.get('nom_complet', 'Utilisateur Inconnu')

                # Vérification des droits d'accès avec l'ID résolu localement
                res_droit = supabase.table("autorisation").select("acces").eq("id_user", user_id).eq("id_porte", id_porte_evenement).execute()

                if res_droit.data and res_droit.data[0]['acces'] is True:
                    print(f"🔓 [ACCÈS ACCORDÉ] {nom_user} (ID: {user_id}) sur {nom_porte_evenement}.")
                    client.publish(f"serrure/{nom_porte_evenement}/commande", "OUVRIR")
                    enregistrer_log("SUCCESS", user_id, badge_scanne, "BADGE + BIOMETRIE", nom_porte_evenement)
                else:
                    print(f"🔒 [ACCÈS REFUSÉ] {nom_user} (ID: {user_id}) n'a pas l'autorisation pour {nom_porte_evenement}.")
                    enregistrer_log("DENIED", user_id, badge_scanne, "BADGE + BIOMETRIE", nom_porte_evenement)
            else:
                print(f"🔒 [ACCÈS REFUSÉ] Aucune correspondance de compte.")
                enregistrer_log("DENIED", None, badge_scanne, "BADGE + BIOMETRIE (INCONNU)", nom_porte_evenement)
        except Exception as e:
            print(f"❌ Erreur double authentification : {e}")

    # 2. Authentification Simple RFID (porte_2)
    elif nom_porte_evenement == "porte_2" and payload.startswith("SCAN_RFID:"):
        try:
            badge_scanne = payload.split(":")[1]
            res_user = supabase.table("utilisateurs").select("*").eq("nfc_id", badge_scanne).execute()
            
            if res_user.data:
                user = res_user.data[0]
                user_id = user['id']
                nom_user = user.get('nom_complet', 'Utilisateur Inconnu')

                # Vérification des droits d'accès avec l'ID résolu localement (2)
                res_droit = supabase.table("autorisation").select("acces").eq("id_user", user_id).eq("id_porte", id_porte_evenement).execute()

                if res_droit.data and res_droit.data[0]['acces'] is True:
                    print(f"🔓 [ACCÈS ACCORDÉ] {nom_user} (ID: {user_id}) sur {nom_porte_evenement} (RFID).")
                    client.publish(f"serrure/{nom_porte_evenement}/commande", "OUVRIR")
                    enregistrer_log("SUCCESS", user_id, badge_scanne, "RFID UNIQUE", nom_porte_evenement)
                else:
                    print(f"🔒 [ACCÈS REFUSÉ] {nom_user} (ID: {user_id}) non autorisé sur {nom_porte_evenement}.")
                    enregistrer_log("DENIED", user_id, badge_scanne, "RFID UNIQUE", nom_porte_evenement)
            else:
                print(f"🔒 [ACCÈS REFUSÉ] Badge inconnu sur {nom_porte_evenement}.")
                enregistrer_log("DENIED", None, badge_scanne, "RFID UNIQUE (INCONNU)", nom_porte_evenement)
        except Exception as e:
            print(f"❌ Erreur authentification simple RFID : {e}")

    # 3. Log Bouton Sortie
    elif payload == "BOUTON_SORTIE":
        print(f"🚪 Sortie détectée manuellement sur la {nom_porte_evenement}")
        enregistrer_log("BOUTON_SORTIE", None, "N/A", "BOUTON INTERNE", nom_porte_evenement)

    # 4. Inscription NFC globale
    elif payload.startswith("CHECK_NFC:"):
        badge_uid = payload.split(":")[1]
        try:
            check_nfc = supabase.table("utilisateurs").select("id").eq("nfc_id", badge_uid).execute()
            cmd_res = supabase.table("commandes_mqtt").select("id").eq("action", "START_NFC").eq("execute", True).order("id", desc=True).limit(1).execute()
            
            if cmd_res.data:
                last_id = cmd_res.data[0]['id']
                if check_nfc.data:
                    print(f"⚠️ [DOUBLON NFC] Le badge {badge_uid} existe déjà.")
                    supabase.table("commandes_mqtt").update({"valeur_nfc": "ERREUR_DOUBLON"}).eq("id", last_id).execute()
                else:
                    supabase.table("commandes_mqtt").update({"valeur_nfc": badge_uid}).eq("id", last_id).execute()
                    print(f"✅ Valeur NFC enregistrée : {badge_uid}")
        except Exception as e:
            print(f"❌ Erreur CHECK_NFC : {e}")

    # 5. Inscription Empreinte (Spécifique porte 1)
    elif payload.startswith("CHECK_FINGER:"):
        status_finger = payload.split(":")[1]
        try:
            cmd_res = supabase.table("commandes_mqtt").select("id").eq("action", "START_ENROLL").eq("execute", True).order("id", desc=True).limit(1).execute()
            
            if cmd_res.data:
                last_id = cmd_res.data[0]['id']
                
                if status_finger == "ERREUR_DOUBLON_PHYSIQUE":
                    print("⚠️ [DOUBLON BIOMÉTRIQUE] Empreinte déjà enregistrée physiquement.")
                    supabase.table("commandes_mqtt").update({"valeur_fingerprint": "DOUBLON_PHYSIQUE"}).eq("id", last_id).execute()
                    return
                
                if status_finger.isdigit():
                    slot_id = int(status_finger)
                    check_finger = supabase.table("utilisateurs").select("id").eq("fingerprint_id", slot_id).execute()
                    
                    if check_finger.data:
                        print(f"⚠️ [DOUBLON SLOT] Le slot {slot_id} est déjà pris.")
                        supabase.table("commandes_mqtt").update({"valeur_fingerprint": "ERREUR_SLOT_OCCUPE"}).eq("id", last_id).execute()
                        return

                supabase.table("commandes_mqtt").update({"valeur_fingerprint": status_finger}).eq("id", last_id).execute()
                print(f"✅ Colonne 'valeur_fingerprint' mise à jour : {status_finger}")
        except Exception as e:
            print(f"❌ Erreur CHECK_FINGER : {e}")

    # 6. Retour Active Directory
    elif topic == TOPIC_CONFIRM_AD:
        try:
            data = payload.split("|")
            status, username = data[0], data[1]
            res = supabase.table("commandes_mqtt").select("id").eq("action", "CHECK_LDAP").eq("valeur_ad", username).eq("execute", True).order("id", desc=True).limit(1).execute()
            if res.data:
                cmd_id = res.data[0]['id']
                db_status = "VALID" if status == "OK" else "NOT_FOUND"
                supabase.table("commandes_mqtt").update({"ad_status": db_status}).eq("id", cmd_id).execute()
                print(f"✅ Statut AD mis à jour pour {username} : {db_status}")
        except Exception as e:
            print(f"⚠️ Erreur retour AD : {e}")

# --- INITIALISATION MQTT ---
client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_BROKER, 1883, 60)
client.loop_start()

print("🚀 VPS UNIVERSEL RE-LANCÉ (CORRIGÉ ET OPÉRATIONNEL)...")

# --- BOUCLE PRINCIPALE : SCRUTATION SUPABASE ---
while True:
    try:
        res = supabase.table("commandes_mqtt").select("*").eq("execute", False).order("id", desc=True).limit(1).execute()
        
        if res.data:
            cmd = res.data[0]
            print(f"\n⚡ Nouvelle commande détectée (ID: {cmd['id']}) : Action = {cmd['action']}")
            supabase.table("commandes_mqtt").update({"execute": True}).eq("id", cmd['id']).execute()
            
            porte_cible = cmd.get("porte", "porte_1")
            topic_commande_dynamique = f"serrure/{porte_cible}/commande"
            
            if cmd['action'] == "START_NFC": 
                client.publish(topic_commande_dynamique, "SCAN_NFC")
                print(f"📡 Ordre envoyé à {porte_cible} : SCAN_NFC")
                
            elif cmd['action'] == "START_ENROLL": 
                try:
                    res_user = supabase.table("utilisateurs").select("fingerprint_id").execute()
                    occupied_slots = set()
                    if res_user.data:
                        for u in res_user.data:
                            val = u.get('fingerprint_id')
                            if val is not None and str(val).isdigit():
                                occupied_slots.add(int(val))
                    next_id = 1
                    while next_id in occupied_slots:
                        next_id += 1
                except Exception as err_calc:
                    print(f"⚠️ Erreur calcul ID libre : {err_calc}")
                    next_id = 1
                
                client.publish(topic_commande_dynamique, f"SCAN_FINGER:{next_id}")
                print(f"🚀 Slot libre {next_id} envoyé à l'ESP32 ciblé : {porte_cible}")
                
            elif cmd['action'] == "OUVRIR": 
                client.publish(topic_commande_dynamique, "OUVRIR")
                print(f"📡 Ordre d'ouverture distant envoyé à : {porte_cible}")
                enregistrer_log("SUCCESS", None, "N/A", "APPLICATION FLUTTERFLOW", porte_cible)
                
            elif cmd['action'] == "CHECK_LDAP":
                client.publish(TOPIC_SYNC_AD, f"{cmd['valeur_ad']}")
                print(f"📡 Ordre AD envoyé : {cmd['valeur_ad']}")
                
            elif cmd['action'] == "START_DELETE":
                valeur_recue = str(cmd.get('valeur_fingerprint', '')).strip()
                id_user_a_supprimer = None
                
                if valeur_recue.startswith("{"):
                    try:
                        data_json = json.loads(valeur_recue)
                        id_user_a_supprimer = data_json.get("id_user")
                    except:
                        pass
                
                if id_user_a_supprimer is None:
                    chiffres = "".join([c for c in valeur_recue if c.isdigit()])
                    if chiffres:
                        id_user_a_supprimer = int(chiffres)
                
                if id_user_a_supprimer:
                    print(f"🔍 Recherche des informations pour l'utilisateur ID: {id_user_a_supprimer}...")
                    user_res = supabase.table("utilisateurs").select("fingerprint_id").eq("id", id_user_a_supprimer).execute()
                    
                    if user_res.data:
                        slot_materiel = user_res.data[0].get('fingerprint_id')
                        
                        if slot_materiel is not None and str(slot_materiel).isdigit():
                            slot_pur = int(slot_materiel)
                            print(f"🎯 Slot d'empreinte identifié : {slot_pur}. Suppression physique envoyée à la porte_1...")
                            client.publish("serrure/porte_1/commande", f"SUPPRIMER_SLOT:{slot_pur}")
                        
                        print(f"🧹 Suppression des autorisations associées à l'utilisateur {id_user_a_supprimer}...")
                        supabase.table("autorisation").delete().eq("id_user", id_user_a_supprimer).execute()
                        
                        print(f"🗑️ Suppression définitive de l'utilisateur {id_user_a_supprimer}...")
                        supabase.table("utilisateurs").delete().eq("id", id_user_a_supprimer).execute()
                        print("✅ Nettoyage de la base de données terminé avec succès !")
                    else:
                        print(f"⚠️ Impossible de supprimer : Aucun utilisateur trouvé avec l'ID {id_user_a_supprimer}.")
                else:
                    print("⚠️ Action START_DELETE reçue sans ID valide.")

    except Exception as e:
        print(f"❌ Erreur dans la boucle principale : {e}")
    time.sleep(1)
