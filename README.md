# 🎮 Manette Souris

Transforme une manette Xbox (ou toute manette XInput) en **souris Windows**, avec un **clavier virtuel intégré** entièrement pilotable à la manette.

Un seul fichier Python, **zéro dépendance** — uniquement la bibliothèque standard (`ctypes` + `tkinter`).

![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078d7)
![Python](https://img.shields.io/badge/Python-3.8%2B-3776ab)
![Dépendances](https://img.shields.io/badge/d%C3%A9pendances-aucune-success)

## ✨ Fonctionnalités

- **Souris fluide** : polling à 1000 Hz via un timer haute résolution Windows, vitesse en pixels/seconde indépendante de la cadence, courbe de précision (lent au centre du stick, rapide au bord)
- **Consommation quasi nulle au repos** : la boucle se cale sur `dwPacketNumber` et ne traite que les changements d'état de la manette
- **Clavier virtuel** navigable à la croix directionnelle, avec sélection visuelle des touches
- **Dispositions AZERTY / QWERTY / QWERTZ**, détectées automatiquement depuis Windows, changeables à la volée
- **Frappe en Unicode** : ce qui est affiché est ce qui est tapé, quelle que soit la disposition active du système
- Le clavier **ne prend jamais le focus** (`WS_EX_NOACTIVATE`) : le texte part toujours dans l'application active
- Clavier **déplaçable et redimensionnable** à la manette (échelle ×0,5 à ×2,5)

## 🚀 Lancement

Prérequis : Windows 10/11, Python 3, une manette XInput (Xbox, 8BitDo, etc.).

Double-clique sur **`Lancer manette souris.bat`**, ou :

```
python manette_souris.py            # disposition auto-détectée
python manette_souris.py qwerty     # forcer une disposition (azerty/qwerty/qwertz)
```

## 🕹️ Commandes

### Mode souris

| Manette | Action |
|---|---|
| Stick gauche | Déplacer le curseur |
| Stick droit | Molette (vertical + horizontal) |
| A | Clic gauche (maintien = glisser-déposer) |
| B | Clic droit |
| X | Clic milieu |
| Y | Ouvrir/fermer le clavier virtuel |
| RB (maintenu) | Mode lent (précision) |
| LB (maintenu) | Mode rapide |
| START + BACK | Quitter |

### Clavier virtuel ouvert

| Manette | Action |
|---|---|
| Croix | Sélectionner une touche (maintien = répétition) |
| A | Appuyer sur la touche sélectionnée |
| X | Effacer (rappelé par Ⓧ sur la touche ⌫) |
| B | Espace (rappelé par Ⓑ sur la barre d'espace) |
| START + stick gauche | Déplacer le clavier |
| BACK + stick droit | Redimensionner le clavier |
| Y | Fermer le clavier |

Les sticks continuent de piloter le curseur et la molette pendant la frappe.

## ⚙️ Réglages

Les vitesses se règlent en tête de la section « Boucle » de [`manette_souris.py`](manette_souris.py) :

```python
POLL_HZ = 1000         # fréquence de lecture de la manette
BASE_SPEED = 1600.0    # vitesse max du curseur (pixels/seconde)
SCROLL_SPEED = 4200.0  # vitesse de la molette
```
