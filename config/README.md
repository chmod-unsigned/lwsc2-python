# Configuration YAML du Moteur

Ce dossier contient toute la logique métier et visuelle du bot. Le moteur est conçu pour être modulaire, performant (multithreading NOGIL), et séparer l'aspect visuel de la logique d'état.

Voici le guide complet de tous les attributs disponibles dans chaque fichier.

---

## 1. `rois.yaml` (Régions d'Intérêt)
Définit les zones de l'écran où le moteur doit chercher des images. Les ROIs sont calculées dynamiquement selon la taille de la fenêtre de jeu.

### Attributs disponibles pour une ROI :
- **`x` / `y`** : Coordonnées de départ.
  - Entier positif : pixels depuis le haut/gauche.
  - Entier négatif : pixels depuis le bas/droite (ex: `-100`).
  - Mots-clés : `"center"` ou `"middle"`.
  - Décalages : `"center -50px"`.
- **`width` / `height`** : Dimensions.
  - Entier : pixels absolus.
  - Entier négatif : décalage depuis le bord opposé (ex: `-200` s'arrête à 200px du bord droit/bas).
  - Pourcentage : `"50%"`.
  - Mot-clé : `"full"` (taille totale de l'écran).
- **`align` / `anchor`** : Centrage automatique si `x` ou `y` n'est pas défini (`"center"`, `"horizontal"`, `"vertical"`).
- **`states`** : *(Liste de strings)* Si défini, cette ROI ne sera analysée que si le jeu se trouve dans l'un de ces états.
- **`exclude`** : *(Liste de strings)* Noms d'autres ROIs à **masquer/ignorer** à l'intérieur de cette ROI. Leurs pixels seront peints en noir absolu avant l'analyse.

> **Astuce :** Utilise les ancres YAML (`&nom`) et les alias (`<<: *nom`) pour éviter de répéter les mêmes géométries (ex: `standard_modal`).

---

## 2. `states.yaml` (Machine à États)
Définit les écrans ou menus du jeu. Le moteur identifie l'état actuel pour savoir quelles actions sont possibles.

### Attributs d'un État :
- **`priority`** : *(Entier)* Ordre d'évaluation. Les priorités élevées (ex: 3 pour une modale) sont testées avant les priorités basses (ex: 1 pour la carte principale).
- **`parent`** : *(String ou Liste)* Définit la hiérarchie. Le moteur utilise le *State Tree Pruning* : il ne cherche que les enfants de l'état courant (et l'état lui-même) pour économiser 80% du CPU. (ex: `parent: [headquarter, area]`).
- **`threshold`** : *(Float)* Seuil de détection global pour cet état (par défaut `0.90`).
- **`requires`** : *(Dictionnaire)* Les conditions visuelles requises pour valider cet état. La clé est le **nom de la ROI**, la valeur est un dictionnaire :
  - **`template`** : Nom de l'image (ou liste d'images) dans `templates/`.
  - **`threshold`** : Seuil spécifique à ce template (0.0 à 1.0).
  - **`color`** : `true` (par défaut) pour match RVB, `false` pour match Niveaux de Gris.
  - **`method`** : `"exact"` (par défaut, très rapide, pixel parfait) ou `"feature"` (OpenCV ORB, plus lent mais gère les zooms et les changements de décor).

---

## 3. `buttons.yaml` (Boutons et POIs)
Définit les éléments cliquables dans les différentes ROIs. Un bouton ne contient **pas de logique d'état** (il est injecté dynamiquement dans les actions).

### Attributs d'un Bouton :
- **`roi`** : *(String)* Nom de la ROI dans laquelle le bouton peut apparaître.
- **`template`** : *(String ou Liste)* Image(s) à trouver.
- **`threshold`** : *(Float)* Seuil de détection (par défaut `0.85`).
- **`color`** : *(Booléen)* `true` (par défaut) ou `false`.
- **`method`** : `"exact"` (par défaut) ou `"feature"` (idéal pour les monstres ou ressources sur la carte).

---

## 4. `actions.yaml` (Actions du Bot)
Définit ce que le bot peut faire. Une action lie des états de jeu, des boutons visuels et une exécution physique (clic ou drag).

### Attributs d'une Action :
- **`label`** : *(String)* Nom d'affichage dans l'interface utilisateur.
- **`states`** : *(Liste)* États dans lesquels cette action a le droit de s'exécuter.
- **`buttons`** : *(Liste)* Liste des boutons associés. Si l'un de ces boutons est visible à l'écran, le clic s'effectuera dessus en priorité. *(Note : si l'action contient des boutons, elle sera cachée de l'interface tant qu'aucun de ses boutons n'est visible à l'écran, sauf si `always_show` est activé).*
- **`always_show`** : *(Booléen)* Si `true`, force l'affichage du bouton d'action dans l'interface même si ses boutons associés ne sont pas actuellement visibles à l'écran (très utile pour des POIs comme des mines).
- **`hold_duration`** : *(Float)* Maintenir le clic pendant X secondes.
- **`cooldown`** : *(Float)* Temps de recharge (en secondes) avant de pouvoir relancer cette action.
- **`save_mouse`** : *(Booléen)* Si `true`, le bot replace la souris à sa position initiale après le clic ou le drag.
- **`variant`** : *(String)* Couleur du bouton dans l'interface Textual (ex: `"primary"`, `"error"`, `"success"`).
- **`drag`** : *(Dictionnaire)* Active le mode Glisser-Déposer au lieu du clic classique. Supporte 3 types :
  
  **Type 1 : Relatif (Mouvement depuis le bouton trouvé)**
  ```yaml
  drag:
    type: relative
    dx: 150       # Pixels vers la droite
    dy: -50       # Pixels vers le haut
    duration: 0.5
  ```

  **Type 2 : ROI à ROI (Absolu lié aux régions)**
  ```yaml
  drag:
    type: roi
    start: roi_depart
    end: roi_arrivee
    duration: 0.5
  ```

  **Type 3 : Coordonnées Libres (Absolu / Écran)**
  ```yaml
  drag:
    type: ab
    from:
      x: -100px   # 100px depuis le bord droit
      y: center
    to:
      x: 100px    # 100px depuis le bord gauche
      y: center
    duration: 0.5
  ```
