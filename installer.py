"""Un bouton sous chaque réponse : la fonction Action « Rendre en 3D » d'Open WebUI.

Fait ce que le module 5 de la série « Intégrations IA » montre à l'écran :
  1. la fonction « Rendre en 3D » (open-webui/rendre_3d.py), identifiant rendre_en_3d ;
  2. ses vannes : adresse interne du studio, jeton du studio (lu dans .env, jamais affiché),
     modèle de l'instance qui traduit la réponse en script de scène ;
  3. la fonction activée ;
  4. la fonction rendue globale : le bouton apparaît sous les réponses de tous les modèles.

Côté studio, les routes /api/assets, /api/soumettre et /api/etat/<n> sont dans
studio/integrations.py (voir README.md).

Usage :
  python installer.py              # installe (ou met à jour)
  python installer.py --retirer    # retire la fonction

Réglages : fichier .env (voir .env.example) ; les variables d'environnement l'emportent.
Aucune dépendance : Python 3.10 ou plus récent, bibliothèque standard seulement.
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ICI = pathlib.Path(__file__).resolve().parent
FONCTION = {"id": "rendre_en_3d", "nom": "Rendre en 3D"}  # identifiant déduit du nom, comme à l'écran


def reglages() -> dict:
    """Lit .env (clé=valeur), puis l'environnement, qui l'emporte."""
    r = {"STUDIO_URL": "http://studio.studio3d.svc.cluster.local:8000", "ESSAIS": "3"}
    env = ICI / ".env"
    if env.exists():
        for ligne in env.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#") and "=" in ligne:
                cle, valeur = ligne.split("=", 1)
                r[cle.strip()] = valeur.strip()
    for cle in ("OWUI_URL", "OWUI_JETON", "STUDIO_URL", "STUDIO_JETON", "MODELE_CODE", "ESSAIS"):
        if os.environ.get(cle):
            r[cle] = os.environ[cle]
    return r


R = reglages()


def api(methode: str, chemin: str, corps=None, ok404: bool = False):
    """Appel de l'API d'Open WebUI avec le jeton administrateur."""
    req = urllib.request.Request(R["OWUI_URL"].rstrip("/") + chemin, method=methode,
                                 data=None if corps is None else json.dumps(corps).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {R['OWUI_JETON']}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as rep:
            texte = rep.read().decode()
    except urllib.error.HTTPError as e:
        if ok404 and e.code in (400, 401, 404):
            return None
        sys.exit(f"{methode} {chemin} : {e.code} {e.read().decode()[:300]}")
    return json.loads(texte) if texte else None


def installer() -> None:
    corps = {"id": FONCTION["id"], "name": FONCTION["nom"],
             "content": (ICI / "open-webui" / "rendre_3d.py").read_text(encoding="utf-8"),
             "meta": {"description": "Un bouton sous chaque réponse : le studio 3D calcule la scène décrite",
                      "manifest": {}}}
    # 1. La fonction (Open WebUI la reconnaît comme Action à sa classe « Action »).
    if api("GET", f"/api/v1/functions/id/{FONCTION['id']}", ok404=True):
        api("POST", f"/api/v1/functions/id/{FONCTION['id']}/update", corps)
        print(f"fonction « {FONCTION['nom']} » mise à jour")
    else:
        api("POST", "/api/v1/functions/create", corps)
        print(f"fonction « {FONCTION['nom']} » créée")
    # 2. Les vannes.
    api("POST", f"/api/v1/functions/id/{FONCTION['id']}/valves/update",
        {"studio_url": R["STUDIO_URL"], "jeton": R["STUDIO_JETON"], "modele_code": R["MODELE_CODE"], "essais": int(R["ESSAIS"])})
    print("vannes enregistrées (adresse du studio, jeton, modèle qui écrit le code, essais)")
    # 3 et 4. Activée, puis globale (un appel « toggle » inverse l'état : on lit d'abord).
    f = api("GET", f"/api/v1/functions/id/{FONCTION['id']}")
    if not f["is_active"]:
        api("POST", f"/api/v1/functions/id/{FONCTION['id']}/toggle")
    if not f["is_global"]:
        api("POST", f"/api/v1/functions/id/{FONCTION['id']}/toggle/global")
    print("fonction activée et globale : le bouton « Rendre en 3D » est sous les réponses de tous les modèles")


def retirer() -> None:
    api("DELETE", f"/api/v1/functions/id/{FONCTION['id']}/delete", ok404=True)
    print(f"fonction « {FONCTION['nom']} » retirée")


if __name__ == "__main__":
    requis = ("OWUI_URL", "OWUI_JETON") + (() if "--retirer" in sys.argv else ("STUDIO_JETON", "MODELE_CODE"))
    for cle in requis:
        if not R.get(cle):
            sys.exit(f"réglage manquant : {cle} (voir .env.example)")
    retirer() if "--retirer" in sys.argv else installer()
