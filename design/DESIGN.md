# Probalab : spécification de la nouvelle interface

Ce dossier sert de référence pour refaire l'interface du site (anciennement CoteJuste).

Les fichiers `*.dc.html` sont les **sources de la maquette validée**. Ils sont écrits dans un format de maquette :
- `{{ … }}` sont des trous remplis par le script en bas du fichier ;
- `<sc-for>` est une boucle et `<sc-if>` une condition.

Ils servent de **référence visuelle et de contenu**. Ne copie pas leur mécanique dans le site : reproduis le rendu avec le HTML/CSS/JS du site existant.

| Fichier | Écran |
|---|---|
| `Main.dc.html` | Mobile : accueil (recos + matchs) |
| `Match.dc.html` | Mobile : fiche match |
| `Combine.dc.html` | Mobile : mon combiné |
| `Classement.dc.html` | Mobile : classement avec bascule Points / xG |
| `Desktop.dc.html` | PC : accueil (menu latéral, recos, tableau des matchs, combiné) |
| `DesktopMatch.dc.html` | PC : fiche match en deux colonnes |

Les cotes Betclic visibles dans la maquette sont des exemples. Le site utilise les vraies données.

---

## 1. Principes

- **Sobre, aéré, lisible.** Gros chiffres, phrases courtes, une seule couleur d'accent. Le vert et le rouge sont réservés au verdict (valeur / pas de valeur).
- **L'essentiel d'abord.** Sur mobile, le détail est replié dans des sections. Sur PC, il est visible en deux colonnes.
- **Un seul site, une seule adresse.** Il s'adapte à la largeur de l'écran, et les fonctionnalités sont les mêmes partout.

## 2. Jetons de design

**Police :** Manrope 400 à 800 (Google Fonts), avec un repli sur `system-ui, sans-serif`. Utilise `font-variant-numeric: tabular-nums` pour tous les chiffres.

**Couleurs :**

| Rôle | Valeur |
|---|---|
| Fond de page | `#F3F5F9` |
| Surface (cartes) | `#FFFFFF` |
| Encre principale | `#0E1525` |
| Encre secondaire | `#2A3142`, `#4A5163` |
| Texte discret | `#5F6675` (jamais plus clair, pour garder le contraste) |
| Filets | `#EEF0F4`, `#E6E9F0` |
| Accent | `#3156F5` ; fond doux `#EDF1FF` ; texte `#1F3FBF` |
| Domicile | barre `#2A78D6`, texte `#1F5FB8` |
| Nul | barre `#CDD2DB`, texte `#4A5163` |
| Extérieur | barre `#EB6834`, texte `#B44A1C` |
| Valeur ✓ | fond `#E6F5EA`, texte `#146C2E` |
| Pas de valeur ✕ | fond `#FDECEC`, texte `#A32626` |
| Avertissement / exemple | fond `#FFF4E0`, texte `#8A5300` ou `#6B4300` |
| Carte sombre (combiné) | fond `#0E1525`, texte secondaire `#B9C0CE`, valeur `#7BE29A` |
| Grille des scores (du clair au foncé) | `#EEF4FC #CDE2FB #9EC5F4 #6DA7EC #3987E5 #256ABF #184F95` ; texte blanc à partir du 5e pas |

**Formes :**
- Rayons : cartes 22 à 24 px, lignes de match 16 à 18 px, champs 14 px, pastilles 999 px.
- Ombre des cartes : `0 1px 2px rgba(14,21,37,.05), 0 8px 24px rgba(14,21,37,.06)`.

**Typographie :**
- Titre de page : 28 px sur mobile, 34 px sur PC, graisse 800.
- Titre de carte : 18 à 19 px, graisse 800.
- Texte : 15 px. Petit texte : 13 px. Libellés : 12 px, graisse 600 à 700.
- Gros chiffres : 22 à 36 px, graisse 800.

**Espacements et accessibilité :**
- Marges de page : 18 px sur mobile, 40 px sur PC. Écarts entre blocs : 12 à 24 px.
- Zones cliquables : au moins 44 px. Focus clavier visible. Vrais `<button>`, `<a>` et `<label>`.
- Le vert et le rouge s'accompagnent toujours d'un symbole (✓ ✕) et d'un mot.

## 3. Mise en page selon l'écran

| Largeur | Navigation | Mise en page |
|---|---|---|
| moins de 700 px (téléphone) | barre d'onglets fixe en bas : Accueil, Matchs, Combiné, Stats | une colonne ; détails de la fiche repliés (`<details>`) |
| 700 à 1099 px (iPad vertical) | barre d'onglets en bas | une colonne plus large, recos et cartes 2 par 2 |
| 1100 px et plus (iPad horizontal, PC) | menu latéral : Accueil, Matchs, Combiné, Classement, Bilan, Méthode, bankroll | fiche match en 2 colonnes, sections ouvertes |

L'onglet « Stats » sur mobile regroupe Classement, Bilan et Méthode, avec un sélecteur en haut.

Garde le routage par `#` existant (`#matchs`, `#m-…`, `#classements`, `#bilan`, `#methode`) pour que les liens actuels continuent de marcher.

## 4. Fonctionnalités à conserver (TOUTES)

Coche chaque ligne avant de pousser.

**Accueil / Matchs**
- [ ] Recos du jour : sécu, valeur, combiné du jour et grosse cote, avec toutes leurs règles, raisons, confiance, cote utilisée (Betclic ou moyenne), cote minimale et mise Kelly. Plafond de 40 % et message « Rien d'intéressant aujourd'hui ».
- [ ] Repères du week-end (ancien bloc « À la une » : favori le plus solide, match le plus indécis, plus gros désaccord avec Sportradar), sous forme d'une bande compacte sous les recos.
- [ ] Liste des matchs groupée par jour : filtre par ligue, probabilités 1N2 avec barre, cotes justes, pastille ✓ valeur, étiquette PROV. pour les horaires provisoires.
- [ ] Réglage de la bankroll, enregistré sur l'appareil.
- [ ] Bandeau « X résultats manquants » (rattrapage) et date des dernières données.

**Fiche match**
- [ ] Probabilités modèle, marché et finale, cotes justes, buts attendus, rangs réel et modèle, forme.
- [ ] Comparaison avec Sportradar.
- [ ] Calculateur de valeur sur les **7 paris** (1, N, 2, +2,5, −2,5, les deux marquent oui / non), cotes Betclic pré-remplies quand elles existent, toujours modifiables, verdict et mise Kelly.
- [ ] « Notre avis » : une phrase de verdict, plus les raisons générées automatiquement.
- [ ] Grille complète des scores, les 3 à 5 scores les plus probables, et tous les marchés (double chance, +1,5 / 2,5 / 3,5, les deux marquent, clean sheets).
- [ ] xG et chance : xG pour et contre, saison et 5 derniers matchs, écart buts − xG, phrase d'explication.
- [ ] Stats des équipes : rang de puissance, attaque et défense vs moyenne, bilan domicile / extérieur, matchs sans encaisser, matchs à 3 buts ou plus.
- [ ] Absents et compositions, confrontations directes, avertissement sur les compositions.
- [ ] Bouton « Ajouter au combiné » sur chaque pari.

**Combiné**
- [ ] Panier enregistré sur l'appareil, retrait d'une sélection, une seule sélection par match, alerte à partir de 3 sélections.
- [ ] Cote, chance et valeur combinées : cote Betclic partout, ou cote moyenne partout, jamais un mélange. Gain selon la mise.

**Stats**
- [ ] Classements des 3 ligues : forme (le plus récent à gauche), rang modèle ▲▼, bascule Points / xG.
- [ ] Bilan : courbes et tableau par type de reco, ROI, CLV, taux de réussite, message « échantillon trop petit ».
- [ ] Méthode : backtest, calibration, couverture xG, explications et limites.

**Partout**
- [ ] Pied de page sur les risques du jeu (09 74 75 13 13, interdit aux mineurs).
- [ ] Aucune requête API supplémentaire. La clé ne doit apparaître nulle part.

## 5. Corrections à faire en même temps

- **xG « 5 derniers matchs » :** quand les xG récents manquent, le site affiche des matchs de 2024-25 comme s'ils étaient récents. N'affiche ce bloc que si les 5 matchs datent de la saison en cours. Sinon, écris « xG récents indisponibles ».
- **Renommage :** CoteJuste devient Probalab partout (titre, en-tête, README, page Méthode, textes).
