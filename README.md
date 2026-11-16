# CoteJuste : moteur de prédiction foot + site

Ligue 1, Premier League, LaLiga. Les données se mettent à jour toutes seules chaque matin grâce à API-Football et à GitHub Actions.

## Structure

```
update.py       enchaîne tout : API-Football -> raw/ et cache/ -> export.py -> build.py
engine/
  api_football.py  client API : clé lue dans .env, cache disque, arrêt à 90 requêtes/jour
  names.py      normalisation des noms d'équipes entre les sources (API-Football, Understat…)
  understat.py  xG par match depuis Understat (ou ses copies archive.org), écrit data/xg/
  data.py       chargement des résultats (+ xG associés) et vérifications
  model.py      modèle de Dixon-Coles pondéré dans le temps, sur un mélange xG / buts
  backtest.py   test walk-forward + choix des paramètres (xi, l2 et poids des xG, sur 2024-25)
  export.py     entraîne le modèle final et écrit out/data.json
raw/
  *_2026-27.txt      résultats de la saison en cours (date | journée | dom | buts | buts | ext),
                     complétés chaque jour par update.py : c'est l'archive de la saison
  live_snapshot.py   classement officiel de référence (saisi à la main, daté)
data/
  xg/<ligue>_<saison>.csv   xG Understat par match (versionnés), _sources.json : provenance de chaque fichier
  journal.csv, recos.csv, paris.csv   suivi des cotes, des recos et des paris
site/
  template.html  le site (HTML/CSS/JS, aucune dépendance)
  build.py       injecte data.json dans le gabarit, ce qui produit index.html
.github/workflows/update.yml   la tâche automatique (chaque matin + compositions avant les matchs)
```

## Ce que permet le plan gratuit d'API-Football (vérifié le 13/11/2026)

- 100 requêtes par jour, 10 par minute.
- Les matchs ne sont accessibles **que pour hier, aujourd'hui et demain** (`/fixtures?date=`). Les paramètres `season=2026`, `next`, `last`, `ids` et le classement `/standings` sont refusés.
- Cotes (`/odds?fixture=`), absents (`/injuries?fixture=`) et compositions (`/fixtures/lineups?fixture=`) marchent match par match.

Conséquences :
- chaque matin, les résultats de la veille sont ajoutés à `raw/*.txt`. Un jour manqué reste rattrapable tant que la réponse est dans `cache/` ;
- les matchs à plus de 48 h viennent du calendrier openfootball (« date provisoire », sans cotes ni absents) ;
- la vérification contre le classement officiel utilise `raw/live_snapshot.py`, daté par `SNAPSHOT_DATE`. Pour revérifier, recopie le classement du jour et change la date.

## Lancer à la main (sur ton ordinateur)

```bash
pip install -r requirements.txt
git clone --depth 1 https://github.com/openfootball/football.json.git   # historique 2022-2026
```

Crée un fichier `.env` (jamais envoyé sur GitHub) contenant `API_FOOTBALL_KEY=ta_clé`, puis :

```bash
python update.py              # mise à jour complète, puis ouvre site/index.html
python update.py --budget 5   # pour tester : au plus 5 requêtes
python update.py --offline    # aucune requête : reconstruit le site avec le cache
python update.py --lineups    # compositions des matchs qui commencent dans l'heure
```

`python engine/data.py` affiche les vérifications, et `python engine/backtest.py` recalcule les paramètres (environ 45 s, inutile à chaque fois).

## Combien de requêtes ?

| Étape | Requêtes |
|---|---|
| `/status` (recalage du compteur) | 0 (gratuit) |
| Matchs d'hier, d'aujourd'hui et de demain | 3 |
| Cotes + absents d'un match dans les 48 h | 2 la veille, 2 le jour du match |
| Compositions | 1 à 3 par match, dans l'heure avant le coup d'envoi |
| Cotes de clôture (bilan) | 1 par match, moins de 30 min avant le coup d'envoi |
| Rattrapage des résultats manquants | 0 à 2 (hier et aujourd'hui, seulement si la copie en cache a plus de 30 min) |

Jour sans match : 3 requêtes. Le matin, le script garde 4 requêtes par match du jour pour les compositions et la clôture, et reporte si besoin les rafraîchissements les moins utiles. Le garde-fou s'arrête à 90.

## Résultats manquants

À chaque mise à jour complète, `update.py` cherche les matchs déjà joués sans résultat dans `raw/`. Il compare deux sources : les matchs vus par l'API, dont le coup d'envoi date de plus de 3 h, et le calendrier openfootball (matchs datés d'avant-hier ou plus tôt). Il tente ensuite de les récupérer avec l'API (hier et aujourd'hui), puis avec openfootball. S'il en manque encore :
- un avertissement s'affiche dans GitHub Actions ;
- un bandeau « X résultats manquants » apparaît sur le site, avec la liste des matchs au survol.

Pour le corriger, ajoute le score à la main en haut de `raw/<ligue>_2026-27.txt`. Si le match a été reporté, ajoute-le à `REPORTES` dans `raw/live_snapshot.py`.

## Combinés

Sous chaque match et dans chaque fiche, les boutons 1, N, 2, +2,5 et −2,5 ajoutent une sélection au panier (bouton « Combiné » en bas à droite). Le panier est gardé dans le navigateur. Il affiche :
- la cote combinée (produit des cotes) ;
- les chances selon le modèle et selon le marché (produits des probabilités) ;
- la valeur (cote combinée × chance modèle) ;
- le gain pour ta mise.

Une seule sélection est possible par match, et un avertissement s'affiche au-delà de 3 sélections.

## Réglages : `engine/config.py`

C'est le seul fichier à modifier pour changer :
- le poids du modèle (`W_MODELE`, 0,5) ;
- ton bookmaker (`BOOKMAKER`, « Betclic ») ;
- les seuils des recos, des mises et du bilan.

## Proba finale : modèle + marché

- **Proba marché** : elle part de la cote **moyenne** des bookmakers, marge retirée. `p_marché = (1/cote) ÷ somme des (1/cote)`, sur 3 issues pour le 1N2 et sur 2 pour +/−2,5.
- **Proba finale** = `W × modèle + (1 − W) × marché`, avec W = 0,5. Sans cotes, c'est le modèle seul (« sans marché ») et aucune reco n'est possible.
- **Où elle sert** : la fiche match affiche les trois probas. Le calculateur, le combiné et les recos utilisent la proba finale.
- **Le meilleur W** : à partir de 200 matchs avec cote de clôture, le W qui minimise le log loss est calculé et affiché dans Méthode. Il n'est jamais appliqué automatiquement.

## Recos du jour (en haut de l'onglet Matchs)

**Candidats** : 1, N, 2, +2,5 et −2,5 des matchs pas encore commencés, à moins de 48 h, avec cotes. **Cote de référence** = cote Betclic si l'API la fournit pour ce match et ce pari, sinon la cote moyenne. Valeur = cote de référence × proba finale. Pour un combiné : produit des cotes Betclic si toutes les sélections en ont une, sinon produit des cotes moyennes (jamais un mélange). La meilleure cote n'est affichée qu'à titre indicatif.

**Les quatre recos :**
- **Sécu** : proba ≥ 65 %, cote ≥ 1,30, valeur ≥ 1. On garde la plus haute proba. Cote minimale = 1 ÷ proba.
- **Valeur** : valeur ≥ 1,05 sur le 1N2 et ≥ 1,08 sur les buts, proba ≥ 35 %. On garde la plus haute valeur. Cote minimale = 1,05 ÷ proba.
- **Combiné** : 2 ou 3 matchs différents, chaque proba ≥ 55 %, chance ≥ 30 %, valeur ≥ 1. On garde la plus haute valeur combinée.
- **Grosse cote** (pour s'amuser) : cote ≥ 5 et valeur ≥ 1, mise fixe d'1 €.

**Règles communes :**
- Une sélection n'apparaît pas dans deux recos à la fois, sauf dans le combiné.
- **Confiance** : Élevée si modèle et marché sont d'accord à 5 points près *et* que les absents sont connus ; Moyenne si une seule de ces conditions est remplie ; Faible sinon.
- **Mise** : ¼ de Kelly sur la cote de référence, plafonnée à 5 %, minimum 0,50 €, arrondie à 0,10 €. Le total reste ≤ 40 % de la bankroll : les mises sont réduites, puis la grosse cote et le combiné sont retirés si besoin.
- Si rien ne passe les filtres, le site affiche « Rien d'intéressant aujourd'hui ». Aucune reco n'est jamais forcée.
- **Aucune requête API supplémentaire** : tout est calculé avec les cotes et les absents déjà en cache.

## Suivi des performances (onglet Bilan)

**Les fichiers :**
- `data/journal.csv` : une ligne « releve » à chaque relecture des cotes d'un match à venir, et une ligne « cloture » moins de 30 min avant le match. Chaque ligne contient, pour 1, N, 2, +2,5 et −2,5, les probas modèle, marché et finale, ainsi que les cotes moyenne, meilleure et Betclic.
- `data/recos.csv` : chaque reco au moment où elle apparaît, une par type, par match et par jour (on garde la première). Une ligne par sélection, avec le même `reco_id` pour les sélections d'un combiné.
- `data/paris.csv` : recalculé à chaque fois, série par série.

**Comment les paris sont jugés :**
- **Cote prise** : la cote Betclic si l'API la fournit pour ce match, sinon la cote moyenne. La meilleure cote reste affichée, mais seulement à titre d'information.
- **CLV** = cote prise ÷ cote de clôture − 1, toujours entre deux cotes du même type : Betclic contre Betclic, moyenne contre moyenne.
- **Séries suivies** : sécu, valeur, combiné, grosse cote, « toutes les valeurs, modèle seul » et « toutes les valeurs, proba finale ». Pour chacune : nombre de paris, taux de réussite, ROI pour 1 € et CLV. Sous 50 paris réglés, le site indique « échantillon trop petit pour conclure ».
- Les fichiers s'ouvrent dans Excel (séparateur `;`, virgule décimale). Le robot les enregistre dans le dépôt.

**Limites :**
- Le 13/11/2026, Betclic n'apparaissait pas parmi les bookmakers renvoyés par l'API (une seule réponse vue, en Copa del Rey). Tant qu'il est absent, la cote prise est la moyenne.
- Recos, mises et bilan utilisent exactement la même cote de référence : chaque reco indique laquelle (Betclic ou moyenne). Si ta cote réelle est sous la cote minimale, renonce.

## xG (Understat)

- `python engine/understat.py` récupère les xG de toutes les saisons. `--seasons current` limite à la saison en cours, et `--check` contrôle seulement l'association, sans requête. La mise à jour quotidienne ne redemande que la saison en cours.
- **Sources, dans l'ordre :**
  1. Understat en direct (`getLeagueData`, ou l'ancienne page HTML) ;
  2. ses copies sur archive.org ;
  3. les dernières données enregistrées.

  Une requête à la fois, 5 s d'écart, User-Agent explicite. Si tout échoue, le modèle utilise les buts réels et la mise à jour continue.
- **Au retour d'Understat**, la mise à jour du matin complète automatiquement, une seule fois et en direct, les saisons passées encore incomplètes. Un avertissement apparaît alors dans GitHub Actions (« Understat est de retour… ») : il faut ensuite relancer `python engine/backtest.py` pour recalculer le poids des xG.
- **Le 14/11/2026, Understat était en maintenance**, même dans un navigateur. Les xG viennent donc de copies archivées, incomplètes pour les saisons récentes :

| | 2022-23 | 2023-24 | 2024-25 | 2025-26 | 2026-27 |
|---|---|---|---|---|---|
| Ligue 1 | 379/380 | 306/306 | 306/306 | 36/306 | 0 |
| Premier League | 380/380 | 380/380 | 380/380 | 380/380 | 40/100 |
| LaLiga | 380/380 | 380/380 | 370/370 | 142/380 | 0 |

La Ligue 1 2024-25 et le début de 2025-26 viennent des tirs Understat republiés par le projet ouvert
[worldfootballR_data](https://github.com/JaseZiv/worldfootballR_data/releases/tag/understat_shots) (à jour au 18/09/2025),
additionnés par match avec `engine/xg_backfill.py` (contrôle : écart médian < 0,01 xG avec Understat, scores identiques).
Ce script ne fait qu'ajouter des matchs absents et ne sert qu'une fois, à la main (`pip install pyreadr` nécessaire).

- **Contrôle d'association** (même affiche, date à ± 1 jour) :
  - Ligue 1 : 99,8 % des matchs Understat associés (Nantes-Brest 2024-25 est daté du 7/02 chez openfootball, du 9/02 chez Understat) ;
  - Premier League : 100 % ;
  - LaLiga : 99,2 % ;
  - aucun écart de score. Les quelques matchs non associés manquent dans nos propres résultats (openfootball).

## Ce que vaut le modèle (backtest sur 1 374 matchs jamais vus, 2025-26 et 2026-27)

| | Ancien : buts seuls | Nouveau : xG (a = 0,7) | Naïf |
|---|---|---|---|
| Log loss 1N2 | 1,0019 | **0,9991** | 1,067 |
| RPS | 0,2054 | 0,2045 | 0,227 |
| Bon favori | 50,6 % | 51,3 % | 45 % |
| Brier +/− 2,5 buts (moyenne : 0,2493) | 0,2486 | **0,2471** | |

Les attaques et les défenses sont estimées sur `a × xG + (1 − a) × buts`, avec `a` choisi parmi 0 ; 0,3 ; 0,5 ; 0,7 ; 1 sur la saison 2024-25. Le modèle avec xG fait un peu mieux hors échantillon : il est adopté.

Le gain reste **modeste** (0,0028 de log loss), mais il a plus que doublé depuis que la Ligue 1 2024-25 est complète (16/11/2026 : il était de 0,0011). Il vient de la Premier League (2025-26 : 1,0305 → 1,0245) et de la Ligue 1 (2025-26 : 1,0060 → 0,9975), les deux ligues dont les xG des saisons précédentes sont complets. LaLiga ne bouge pas encore. Il devrait grandir quand Understat reviendra avec les xG de 2025-26 et de la saison en cours.

Le plus/moins de 2,5 buts progresse un peu, mais reste à peine meilleur que la moyenne historique. Les bookmakers restent meilleurs (log loss d'environ 0,97) : une « valeur » affichée par le site est une piste, pas une certitude.

## Idées d'amélioration, par ordre d'impact

1. Compléter les xG récents (Ligue 1, LaLiga) quand Understat sera de nouveau en ligne : relancer `python engine/understat.py`, puis `python engine/backtest.py`.
2. Intégrer au calcul les absents et les compositions (déjà récupérés et affichés).
3. Ajouter la fatigue : matchs de Coupe d'Europe en milieu de semaine, jours de repos.
4. Mesurer le modèle contre les cotes de clôture : c'est le vrai test pour savoir s'il peut battre le marché.
5. Ajouter Serie A et Bundesliga.
