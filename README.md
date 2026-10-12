# Un bouton sous chaque réponse — fonction Action Open WebUI « Rendre en 3D »

Code et configuration de la démonstration du module 5 (dernier module) de la série « Clic par clic »
**Intégrations IA** (Open WebUI relié au studio 3D de l'organisation).

Vidéo : {{video}}

## But

Aux modules 1 à 3, le studio était un **outil** : le modèle de l'assistant décidait de l'appeler. Au
module 4, il devenait un **modèle** (fonction Pipe) : chaque message partait au studio. Ici, c'est
**l'utilisateur** qui décide : une **fonction Action** ajoute un bouton « Rendre en 3D » sous chaque
réponse, quel que soit le modèle. Un clic, une confirmation, et la réponse est traduite en scène 3D,
calculée par le studio, puis affichée dans un widget juste au-dessus du texte.

```
clic « Rendre en 3D » ─▶ Action (serveur d'Open WebUI)
     Action ─__event_call__ « confirmation »─▶ navigateur ─ Confirmer ─▶ Action
     Action ─GET /api/assets─▶ studio                      (la bibliothèque, ajoutée aux consignes)
     Action ─generate_chat_completion─▶ modèle de langage ─▶ titre + script de la scène décrite
     Action : verifier(script) ── refusé ──▶ l'erreur repart au modèle, qui corrige
     Action ─POST /api/soumettre─▶ studio                  (au nom de l'utilisateur)
     Action ─GET /api/etat/<n> toutes les 2 s─▶ studio ─▶ événements « status » sous la réponse
     Action ─▶ HTMLResponse (Content-Disposition: inline) : widget image, objet 3D, scène Blender
```

Contenu, à l'état montré en fin de vidéo :

| Fichier | Rôle |
|---|---|
| `open-webui/rendre_3d.py` | La fonction Action (gardée sous la forme reformatée par Open WebUI à l'enregistrement) : en-tête (nom, description, icône `icon_url` du bouton), vannes (adresse interne du studio, jeton en champ masqué, modèle qui écrit le code, essais), `action()` : réponse cliquée (`reponse_cliquee`), confirmation (`__event_call__`), bibliothèque d'assets dans les consignes, boucle des essais (`ecrire` → `generate_chat_completion`, `decouper`, `verifier`, `corriger`), soumission et suivi (`suivre`, événements `status`), widget (`widget`, `HTMLResponse`) |
| `studio/integrations.py` | Côté studio, routes internes protégées par le jeton du studio et l'adresse de l'utilisateur : `/api/assets`, `/api/soumettre` (même file que l'outil MCP, scène Blender prévue), `/api/etat/<n>` (sa demande seulement). Identique à la copie du module 4 |
| `installer.py` | La fonction, ses vannes, son activation et son passage en « Global », par l'API d'Open WebUI (`--retirer` pour la retirer) |

Les aides `ecrire`, `decouper`, `bibliotheque`, `corriger`, `verifier` et `suivre` sont celles de la
fonction Pipe du module 4, à l'identique : une fonction d'Open WebUI tient dans un seul fichier et ne
peut pas importer une autre fonction.

## Prérequis

- Le studio 3D dans sa dernière version, déployé dans le même cluster qu'Open WebUI : dépôt
  [clic-par-clic-studio3d-06-stockage-s3](https://github.com/guilhem-/clic-par-clic-studio3d-06-stockage-s3)
  (image `studio3d:5`, Redis, workers, bibliothèque d'assets, stockage S3), avec les routes de
  `studio/integrations.py`.
- Open WebUI 0.11 (tourné sur 0.11.3), un compte **administrateur** et son jeton ; un modèle de
  l'instance pour écrire le code.
- Python 3.10 ou plus récent (bibliothèque standard seulement) pour `installer.py`.

## Installation pas à pas

### 1. Les routes du studio

Si vous avez suivi le module 4, elles sont déjà là. Sinon, `integrations.py` s'ajoute à l'image du
studio (`api.py` le charge s'il est présent) :

```bash
cp studio/integrations.py ../clic-par-clic-studio3d-06-stockage-s3/studio/
# Dockerfile : COPY commun.py api.py travailleur.py … integrations.py ./
docker build -t studio3d:5 ../clic-par-clic-studio3d-06-stockage-s3/studio
k3d image import studio3d:5 -c <votre cluster>     # avec k3d ; sinon, poussez l'image dans votre registre
kubectl rollout restart deployment/studio-api -n studio3d
```

Ces routes restent internes au cluster : aucun Ingress ne les publie.

### 2. À la main, comme dans la vidéo

1. **Panneau d'administration › Fonctions › Créer** : nom « Rendre en 3D » (l'identifiant
   `rendre_en_3d` s'en déduit) ; collez le contenu de `open-webui/rendre_3d.py` dans l'éditeur ;
   **Enregistrer & Créer**, puis **Confirmer**. Open WebUI reconnaît une Action à sa classe `Action`
   (badge ACTION dans la liste).
2. Dans la liste des fonctions, activez « Rendre en 3D », puis ouvrez ses **Vannes** : collez le jeton
   du studio (champ masqué) ; indiquez l'identifiant du modèle qui écrit le code ; **Enregistrer**.
3. Menu **…** de la fonction › **Global** : le bouton apparaît sous les réponses de tous les modèles.
   (Sans « Global », on coche l'action modèle par modèle : Réglages › Modèles › Modifier › Actions.)

### 3. Ou par le script

```bash
cp .env.example .env          # OWUI_URL, OWUI_JETON, STUDIO_URL, STUDIO_JETON, MODELE_CODE
python installer.py           # fonction, vannes, activation, Global
python installer.py --retirer # retire la fonction
```

## Essai

Avec n'importe quel compte et son modèle habituel : « Imagine en trois phrases courtes un coin lecture
pour l'accueil de notre showroom, avec un fauteuil moderne et un vase en céramique, dans une ambiance
boisée. » Sous la réponse, cliquez sur le cube « Rendre en 3D », puis **Confirmer**. Sous le nom du
modèle, l'état défile : bibliothèque, traduction en scène, file d'attente, calcul sur un worker. Puis le
widget, au-dessus du texte (inchangé) : l'image, l'objet 3D à faire tourner, le lien « Télécharger la
scène Blender », les assets utilisés et le marquage.

## Cinq façons de relier un service à Open WebUI

| Méthode (module) | Qui décide | Quand l'utiliser | Limites |
|---|---|---|---|
| Serveur MCP (1) | le modèle | un service partagé, appelé au fil de la conversation | le modèle peut ne pas l'appeler |
| Message direct (2) | le service, à la fin du rendu | prévenir d'un résultat long, hors de la conversation | un compte robot ; à sens unique |
| Outil natif et widget (3) | le modèle ; le widget suit seul | suivre un calcul en direct dans la réponse | code exécuté sur le serveur d'Open WebUI |
| Fonction Pipe (4) | le code | un déroulé maîtrisé, vérifié, de bout en bout | un modèle à part : chaque message part au service |
| Fonction Action (5) | l'utilisateur, d'un clic | agir sur une réponse existante, à la demande | un clic par rendu, pas d'enchaînement automatique |

## Sécurité

- Le jeton du studio reste dans les vannes de la fonction, sur le serveur d'Open WebUI (champ masqué).
- Rien ne part au studio sans la confirmation de l'utilisateur (`__event_call__`).
- L'Action appelle le studio au nom de l'utilisateur connecté (`X-Utilisateur-Email`) ; `/api/etat` ne
  renvoie que ses propres demandes ; le modèle de langage est appelé avec ses droits.
- Le widget est une page isolée dans un cadre ; chaque valeur venue du studio y est échappée
  (`html.escape`).
- Aucun secret dans ce dépôt (`.env` est ignoré par git).

## Série

- Module précédent : **Le studio comme un modèle : une fonction Pipe** —
  [clic-par-clic-integration-04-fonction-pipe](https://github.com/guilhem-/clic-par-clic-integration-04-fonction-pipe).
- C'est le dernier module de la série. À suivre : la série **« n8n et Open WebUI »** (un assistant qui
  agit dans vos processus).
- Construire le studio : série « Créer un service d'IA compatible agentique : le studio 3D »
  (dépôts `clic-par-clic-studio3d-01` à `06`).

## Licence

MIT (voir `LICENSE`).
