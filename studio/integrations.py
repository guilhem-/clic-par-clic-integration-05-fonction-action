"""Studio 3D à l'échelle — routes de la série Intégrations, branchées sur le serveur MCP (api.py).

Absentes du dépôt du module s3d02 : api.py les charge seulement si ce fichier est présent.
  /s/<n>/<signature>   état public signé d'une demande (widget de suivi, module int03)
  /api/soumettre       soumission directe (fonction Pipe « Studio 3D », module int04)
  /api/etat/<n>        état d'une demande de l'appelant (fonction Pipe, module int04)
  /api/suivi/<n>       adresse d'état signée (outil « Suivi des rendus », module int03)
  /api/assets          bibliothèque d'assets, pour les consignes de la fonction Pipe (module int04)
"""
import hmac
import time
import uuid

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

import commun as c
import metriques as m  # module s3d03 : ces routes comptent aussi leurs appels


def brancher(mcp, r, _position) -> None:
    """Ajoute les routes au serveur `mcp` ; `r` : connexion Redis ; `_position` : position d'une demande en file."""

    def _libelle(nom: str) -> str:
        """Nom lisible d'un asset du catalogue, dans la langue du studio."""
        cat = c.catalogue()
        fiche = cat["modeles"].get(nom) or cat["environnements"].get(nom) or {}
        return fiche.get("nom", {}).get(c.LANGUE) or fiche.get("nom", {}).get("FR") or nom

    def _etat_public(numero: int) -> dict | None:
        """État d'une demande sans identité ni code : ce que montre le widget de suivi (module int03).
        Terminée : image, objet 3D, scène Blender, assets utilisés et marquage, comme etat_rendu."""
        d = {c.texte(k): c.texte(v) for k, v in r.hgetall(c.demande(numero)).items()}
        if not d:
            return None
        etat = {"numero": numero, "titre": d["titre"], "statut": d["statut"]}
        if d["statut"] == "en_attente":
            etat["position"] = _position(numero)
        elif d["statut"] == "en_cours":
            etat["depuis_secondes"] = round(time.time() - float(d["debut"]))
            etat["travailleur"] = d.get("travailleur", "")
        elif d["statut"] == "termine":
            etat.update(duree_secondes=round(float(d["fin"]) - float(d["debut"])), travailleur=d.get("travailleur", ""),
                        png=c.lien(numero, "png"), glb=c.lien(numero, "glb"),
                        # Marquage (module s3d04) : invisible toujours (métadonnées), bandeau visible sur demande.
                        marquage_visible=d.get("marquage_visible") == "1")
            if d.get("assets"):  # module s3d05 : assets de la bibliothèque utilisés (libellé et licence)
                etat["assets"] = [{"libelle": _libelle(a["nom"]), "licence": a["licence"]}
                                  for a in c.trace_assets(d["assets"].split(","))]
            if d.get("scene") and time.time() <= float(d["fin"]) + c.DUREE_SCENES:
                etat["scene"] = c.lien(numero, "blend")  # module s3d06 : lien signé, redirigé vers le stockage S3
            elif d.get("scene_prevue") == "1":
                etat["scene"] = "indisponible"
        else:
            etat["erreur"] = (d.get("erreur") or "").strip().splitlines()[-1:] or [""]
            etat["erreur"] = etat["erreur"][0][:200]
        return etat


    @mcp.custom_route("/s/{numero}/{sig}", methods=["GET"])
    async def etat_signe(request: Request) -> Response:
        """État public d'une demande, par lien signé (lu par le widget de suivi depuis le navigateur)."""
        try:
            numero = int(request.path_params["numero"])
        except ValueError:
            return Response(status_code=404)
        etat = _etat_public(numero) if hmac.compare_digest(request.path_params["sig"], c.signature(numero, "etat")) else None
        if etat is None:
            return Response(status_code=404)
        return JSONResponse(etat, headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})


    def _appelant(request: Request) -> str | None:
        """Adresse de l'utilisateur d'un appel interne (jeton du studio obligatoire), sinon None."""
        if request.headers.get("authorization", "") != f"Bearer {c.JETON}":
            return None
        return request.headers.get("x-utilisateur-email", "").strip().lower() or None


    @mcp.custom_route("/api/soumettre", methods=["POST"])
    async def api_soumettre(request: Request) -> Response:
        """Pour la fonction Pipe « Studio 3D » (module int04) : même file que l'outil MCP soumettre_rendu."""
        m.DEMANDES.labels(outil="api_soumettre").inc()
        email = _appelant(request)
        if not email:
            return JSONResponse({"erreur": "jeton ou utilisateur manquant"}, status_code=401)
        corps = await request.json()
        choix = corps.get("marquage_visible")  # facultatif : même politique de marquage que l'outil MCP (module s3d04)
        visible = c.MARQUAGE_IMPOSE or (bool(choix) if choix is not None else c.MARQUAGE_DEFAUT)
        numero = r.incr("studio:compteur")
        r.hset(c.demande(numero), mapping={"numero": numero, "titre": str(corps.get("titre", ""))[:80], "code": corps.get("code", ""),
                                           "utilisateur": email, "utilisateur_id": "", "statut": "en_attente", "soumis": time.time(),
                                           "identifiant": str(uuid.uuid4()), "marquage_visible": "1" if visible else "0", "scene_prevue": "1" if c.STOCKAGE else "0"})
        r.lpush(c.FILE, numero)
        r.lpush(c.CHARGE, numero)
        return JSONResponse({"numero": numero, "position": _position(numero)})


    @mcp.custom_route("/api/etat/{numero}", methods=["GET"])
    async def api_etat(request: Request) -> Response:
        """État d'une demande de l'appelant (fonction Pipe, module int04)."""
        m.DEMANDES.labels(outil="api_etat").inc()
        email = _appelant(request)
        try:
            numero = int(request.path_params["numero"])
        except ValueError:
            return Response(status_code=404)
        if not email or c.texte(r.hget(c.demande(numero), "utilisateur")) != email:
            return JSONResponse({"erreur": "aucune demande de ce numéro pour cet utilisateur"}, status_code=404)
        return JSONResponse(_etat_public(numero))


    @mcp.custom_route("/api/suivi/{numero}", methods=["GET"])
    async def suivi(request: Request) -> Response:
        """Pour l'outil « Suivi des rendus » d'Open WebUI (jeton du studio + adresse de l'utilisateur) :
        renvoie l'adresse d'état signée d'une demande de cet utilisateur."""
        m.DEMANDES.labels(outil="api_suivi").inc()
        if request.headers.get("authorization", "") != f"Bearer {c.JETON}":
            return JSONResponse({"erreur": "jeton du studio invalide"}, status_code=401)
        email = request.headers.get("x-utilisateur-email", "").strip().lower()
        try:
            numero = int(request.path_params["numero"])
        except ValueError:
            return Response(status_code=404)
        if not email or c.texte(r.hget(c.demande(numero), "utilisateur")) != email:
            return JSONResponse({"erreur": "aucune demande de ce numéro pour cet utilisateur"}, status_code=404)
        return JSONResponse({"numero": numero, "titre": c.texte(r.hget(c.demande(numero), "titre")),
                             "etat": f"{c.PUBLIC}/s/{numero}/{c.signature(numero, 'etat')}"})


    @mcp.custom_route("/api/assets", methods=["GET"])
    async def api_assets(request: Request) -> Response:
        """Bibliothèque d'assets, pour les consignes de la fonction Pipe (module int04) : le nom à écrire
        dans le code, le libellé et les dimensions (mètres : largeur, profondeur, hauteur)."""
        m.DEMANDES.labels(outil="api_assets").inc()
        if not _appelant(request):
            return JSONResponse({"erreur": "jeton ou utilisateur manquant"}, status_code=401)
        cat = c.catalogue()
        return JSONResponse([{"nom": nom, "genre": genre, "libelle": f["nom"].get(c.LANGUE, f["nom"]["FR"]),
                              "dimensions_m": f.get("dimensions_m")}
                             for genre, cle in (("modele", "modeles"), ("environnement", "environnements"))
                             for nom, f in cat[cle].items()])
