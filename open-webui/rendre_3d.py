"""
title: Rendre en 3D
description: Un bouton sous chaque réponse : le studio 3D calcule la scène décrite, le rendu s'affiche dessous.
icon_url: https://cdn.jsdelivr.net/npm/lucide-static@0.460.0/icons/box.svg
version: 2.0
"""

# Fonction « Action » d'Open WebUI (Panneau d'administration › Fonctions) : un bouton sous chaque
# réponse. C'est l'utilisateur qui déclenche, d'un clic, après confirmation. Un modèle de langage
# traduit la réponse en script Blender (bibliothèque d'assets du studio dans les consignes),
# l'Action le vérifie, le soumet au studio, publie l'avancement, puis affiche le résultat sous la
# réponse, dans un widget : image, objet 3D, scène Blender, assets et marquage.
# Mêmes aides que la fonction Pipe du module 4 (ecrire, decouper, verifier, suivre) : une fonction
# Open WebUI tient dans un seul fichier.

import asyncio
import html
import json
import re

import aiohttp
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

CONSIGNE = """Tu écris un script Python pour Blender 5.2 (module bpy) qui construit, dans une scène vide, la scène décrite dans le texte fourni.
Script court et à plat : un sol nommé « Decor sol », les objets décrits, rien d'autre.
Dès qu'un objet ou un éclairage figure dans la bibliothèque ci-dessous, utilise-le : charger_asset("nom", position=(x, y, z)) et environnement("nom"), sans import, chaque appel au début de sa ligne, sans indentation.
position est celle de la base de l'objet : z = 0 au sol ; posé sur un autre objet, z = hauteur de celui-ci (dimensions en mètres : largeur × profondeur × hauteur).
Donne un nom commençant par « Decor » à tout ce qui n'est pas le sujet. Couleurs : entrée « Base Color » du nœud Principled BSDF.
Caméra facultative, sans profondeur de champ. Ne règle pas le moteur, n'enregistre rien.
Réponds par une ligne « Titre : » de quatre mots au plus, puis un seul bloc de code python.
Bibliothèque du studio :
"""


class Action:
    class Valves(BaseModel):
        studio_url: str = Field(
            "http://studio.studio3d.svc.cluster.local:8000",
            description="Adresse interne du studio",
        )
        jeton: str = Field(
            "",
            description="Jeton du studio",
            json_schema_extra={"input": {"type": "password"}},
        )
        modele_code: str = Field("", description="Modèle qui écrit le code de la scène")
        essais: int = Field(3, description="Essais : code refusé, rendu en échec")

    def __init__(self):
        self.valves = self.Valves()

    async def action(
        self, body, __user__, __request__, __event_emitter__=None, __event_call__=None
    ):
        async def etat(texte: str, fini: bool = False):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": texte, "done": fini}}
                )

        # 1. La réponse sous laquelle l'utilisateur a cliqué.
        texte = reponse_cliquee(body)

        # 2. Confirmation : rien ne part au studio sans l'accord de l'utilisateur.
        ok = await __event_call__(
            {
                "type": "confirmation",
                "data": {
                    "title": "Rendre en 3D",
                    "message": "Envoyer cette réponse au studio 3D ? Un worker va calculer la scène.",
                },
            }
        )
        if ok is not True:  # Annuler, ou fenêtre fermée : on s'arrête là
            return None

        v = self.valves
        entetes = {
            "Authorization": f"Bearer {v.jeton}",
            "X-Utilisateur-Email": __user__["email"],
        }
        async with aiohttp.ClientSession(v.studio_url, headers=entetes) as studio:
            # 3. La bibliothèque du studio dans les consignes ; la réponse, à traduire.
            await etat("Lecture de la bibliothèque du studio…")
            async with studio.get("/api/assets") as r:
                assets = await r.json()
            consigne = CONSIGNE + "\n".join(f"- {bibliotheque(a)}" for a in assets)
            messages = [
                {"role": "system", "content": consigne},
                {"role": "user", "content": texte},
            ]

            for essai in range(1, v.essais + 1):
                # 4. Le modèle de langage traduit la réponse en script, l'Action le vérifie.
                if essai == 1:
                    await etat("Le modèle traduit la réponse en scène 3D…")
                else:
                    await etat(f"Le modèle corrige le code (essai {essai})…")
                sortie = await ecrire(__request__, __user__, v.modele_code, messages)
                messages.append({"role": "assistant", "content": sortie})
                titre, code = decouper(sortie)
                erreur = verifier(code, {a["nom"] for a in assets})
                if erreur:
                    await etat(f"Code refusé : {erreur}")
                    messages.append(corriger(erreur))
                    continue

                # 5. Soumission au nom de l'utilisateur, suivi en direct, puis le widget.
                demande = {"titre": titre, "code": code}
                async with studio.post("/api/soumettre", json=demande) as r:
                    numero = (await r.json())["numero"]
                e = await suivre(studio, numero, titre, etat)
                if e["statut"] == "termine":
                    await etat(
                        f"Rendu n° {numero} prêt en {e['duree_secondes']} s, calculé par {e['travailleur']}",
                        fini=True,
                    )
                    return HTMLResponse(
                        content=widget(e), headers={"Content-Disposition": "inline"}
                    )
                messages.append(corriger(f"Le rendu a échoué : {e.get('erreur', '')}"))

        await etat(f"Le rendu a échoué après {v.essais} essais", fini=True)
        return None


def reponse_cliquee(body: dict) -> str:
    """Texte de la réponse dont on a cliqué le bouton (body["id"]), sinon la dernière."""
    messages = body.get("messages", [])
    cliquee = next((m for m in messages if m.get("id") == body.get("id")), messages[-1])
    return cliquee.get("content", "")


async def ecrire(request, user: dict, modele: str, messages: list) -> str:
    """Appelle un modèle de l'instance, comme une conversation, et renvoie son texte."""
    from open_webui.models.users import Users
    from open_webui.utils.chat import generate_chat_completion

    utilisateur = Users.get_user_by_id(user["id"])
    if asyncio.iscoroutine(utilisateur):
        utilisateur = await utilisateur
    reponse = await generate_chat_completion(
        request, {"model": modele, "stream": False, "messages": messages}, utilisateur
    )
    if hasattr(reponse, "body"):  # réponse HTTP plutôt que dictionnaire
        reponse = json.loads(reponse.body)
    return reponse["choices"][0]["message"]["content"]


def decouper(texte: str) -> tuple[str, str]:
    """Titre (ligne « Titre : ») et code (premier bloc python) d'une réponse du modèle."""
    t = re.search(r"Titre\s*:\s*\**([^\n*]+)", texte)
    bloc = re.search(r"```(?:python)?[^\n]*\n(.*?)(?:```|$)", texte, re.S)
    titre = t.group(1).strip()[:60] if t else "Scène"
    return titre, bloc.group(1) if bloc else texte


def bibliotheque(a: dict) -> str:
    """Une ligne de la bibliothèque, pour les consignes : nom, libellé, genre, dimensions."""
    taille = " × ".join(f"{x:g}" for x in a["dimensions_m"] or [])
    return f"{a['nom']} : {a['libelle']} ({a['genre']}{', ' + taille + ' m' if taille else ''})"


def corriger(probleme: str) -> dict:
    """Message renvoyé au modèle de langage : le problème, et ce qu'on attend de lui."""
    return {
        "role": "user",
        "content": f"{probleme}. Renvoie le script complet corrigé.",
    }


def verifier(code: str, noms: set) -> str | None:
    """Ce qui ferait échouer le rendu, ou None : le message renvoyé au modèle pour correction."""
    try:
        compile(code, "scene.py", "exec")
    except SyntaxError as err:
        return f"Ton code ne compile pas, ligne {err.lineno} : {err.msg}"
    appels = re.findall(r"(?:charger_asset|environnement)\(\s*[\"']([^\"']+)", code)
    inconnus = sorted(set(appels) - noms)
    if inconnus:
        return f"Assets absents de la bibliothèque : {', '.join(inconnus)}"
    if re.search(r"use_dof\s*=\s*True", code):
        return "Pas de profondeur de champ (use_dof)"
    return None


async def suivre(studio, numero: int, titre: str, etat) -> dict:
    """Lit l'état de la demande toutes les deux secondes et le publie ; renvoie l'état final."""
    while True:
        async with studio.get(f"/api/etat/{numero}") as r:
            e = await r.json()
        if e["statut"] == "en_attente":
            position = e["position"]
            await etat(
                f"Demande n° {numero} « {titre} » : dans la file, position {position}"
            )
        elif e["statut"] == "en_cours":
            worker, depuis = e["travailleur"], e["depuis_secondes"]
            await etat(f"Demande n° {numero} : calcul sur {worker} depuis {depuis} s")
        else:
            return e
        await asyncio.sleep(2)


def widget(e: dict) -> str:
    """Le widget affiché sous la réponse : image, objet 3D, scène Blender, assets, marquage."""
    x = lambda valeur: html.escape(str(valeur))  # rien de brut dans la page
    pied = []
    if str(e.get("scene", "")).startswith("http"):
        lien = x(e["scene"])
        pied.append(
            f'<a id="scene" href="{lien}" target="_blank">Télécharger la scène Blender</a>'
        )
    elif e.get("scene"):
        pied.append('<span id="scene">Scène Blender indisponible</span>')
    if e.get("assets"):
        libelles = " · ".join(a["libelle"] for a in e["assets"])
        pied.append(f'<span id="assets">Assets : {x(libelles)}</span>')
    marquage = "métadonnées et bandeau" if e.get("marquage_visible") else "métadonnées"
    pied.append(f'<span id="marquage">Marqué IA : {marquage}</span>')
    return (
        WIDGET.replace("__TITRE__", x(e["titre"]))
        .replace("__NUMERO__", x(e["numero"]))
        .replace("__DUREE__", x(e["duree_secondes"]))
        .replace("__PNG__", x(e["png"]))
        .replace("__GLB__", x(e["glb"]))
        .replace("__PIED__", "".join(pied))
    )


WIDGET = r"""<!doctype html><html><head><meta charset="utf-8">
<script type="module" src="https://cdn.jsdelivr.net/npm/@google/model-viewer@4.0.0/dist/model-viewer.min.js"></script>
<style>
  :root { color-scheme: light dark; --fond:#f8fafc; --texte:#0f172a; --doux:#64748b; --accent:#0891b2; --cadre:#e2e8f0; }
  @media (prefers-color-scheme: dark) { :root { --fond:#0f172a; --texte:#e2e8f0; --doux:#94a3b8; --cadre:#1e293b; } }
  * { box-sizing:border-box; margin:0; } body { font:19px/1.45 system-ui,'Segoe UI',sans-serif; color:var(--texte); background:transparent; }
  .carte { border:1px solid var(--cadre); border-radius:16px; background:var(--fond); padding:18px 20px; }
  .tete { display:flex; justify-content:space-between; align-items:baseline; gap:12px; }
  .titre { font-weight:650; font-size:21px; } .num { color:var(--doux); font-size:16px; }
  .vues { display:grid; gap:12px; grid-template-columns:1fr 1fr; margin-top:12px; }
  .vues img { display:block; width:100%; aspect-ratio:16/10; }
  .vues model-viewer { display:block; width:100%; height:100%; min-height:200px; }
  .vues img, .vues model-viewer { border-radius:10px; background:#e5e7eb; object-fit:cover; }
  .pied { display:flex; flex-wrap:wrap; gap:6px 18px; align-items:center; margin-top:12px; font-size:16px; color:var(--doux); }
  .pied a { color:var(--accent); font-weight:600; text-decoration:none; } .pied a:hover { text-decoration:underline; }
</style></head><body>
<div class="carte">
  <div class="tete"><span class="titre">Rendu 3D — __TITRE__</span><span class="num">Demande n° __NUMERO__ · __DUREE__ s</span></div>
  <div class="vues"><img id="image" src="__PNG__" alt="__TITRE__"><model-viewer id="modele" src="__GLB__" poster="__PNG__" camera-controls auto-rotate shadow-intensity="1"></model-viewer></div>
  <div class="pied">__PIED__</div>
</div>
<script>
// Le cadre est isolé : Open WebUI ne peut pas le mesurer, il annonce lui-même sa hauteur.
const hauteur = () => parent.postMessage({ type: 'iframe:height', height: document.documentElement.scrollHeight }, '*');
new ResizeObserver(hauteur).observe(document.body);
</script></body></html>"""
