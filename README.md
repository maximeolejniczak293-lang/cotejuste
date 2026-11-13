# CoteJuste : moteur de prédiction foot + site

Ligue 1, Premier League, LaLiga. Les données se mettent à jour toutes seules chaque matin grâce à API-Football et à GitHub Actions.

## Structure

```
update.py       enchaîne tout : API-Football -> raw/ et cache/ -> export.py -> build.py
engine/
  api_football.py  client API : clé lue dans .env, cache disque, arrêt à 90 requêtes/jour
  names.py      normalisation des noms d'équipes entre les sources (dont API-Football)
  data.py       chargement des résultats + vérifications (classement officiel, journées complètes)
  model.py      modèle de Dixon-Coles pondéré dans le temps
  backtest.py   test walk-forward + choix des paramètres (sur 2024-25 uniquement)
  export.py     entraîne le modèle final et écrit out/data.json
raw/
  *_2026-27.txt      résultats de la saison en cours (date | journée | dom | buts | buts | ext),
                     complétés chaque jour par update.py : c'est l'archive de la saison
  live_snapshot.py   classement officiel de référence (saisi à la main, daté)
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

## Suivi des performances (onglet Bilan)

- `data/journal.csv` : à chaque mise à jour où les cotes d'un match à venir sont relues, une ligne « releve » avec les probabilités du modèle, la cote moyenne et la meilleure cote pour 1, N, 2, +2,5, −2,5. Moins de 30 min avant le match, une ligne « cloture ».
- `data/paris.csv` : recalculé à chaque fois. Ce sont les paris « valeur » (cote moyenne × probabilité ≥ 1,05) pris au dernier relevé avant le match, avec le résultat, le gain pour 1 € et la CLV (cote prise ÷ cote de clôture − 1).
- Les deux fichiers s'ouvrent dans Excel (séparateur `;`, virgule décimale). Le robot les enregistre dans le dépôt après chaque mise à jour.

## Ce que vaut le modèle (backtest sur 1 374 matchs jamais vus)

| | Modèle | Naïf |
|---|---|---|
| Log loss 1N2 | 1,002 | 1,067 |
| RPS | 0,205 | 0,227 |
| Bon favori | 51 % | 45 % |

La calibration est bonne sur le 1N2. En revanche, le modèle n'apporte quasiment rien sur le plus/moins de 2,5 buts. Les bookmakers restent un peu meilleurs (log loss d'environ 0,97). Une « valeur » affichée par le site est donc une piste, pas une certitude.

## Idées d'amélioration, par ordre d'impact

1. Ajouter les xG (FBref, Understat), qui prédisent mieux que les buts réels.
2. Intégrer au calcul les absents et les compositions (déjà récupérés et affichés).
3. Ajouter la fatigue : matchs de Coupe d'Europe en milieu de semaine, jours de repos.
4. Mesurer le modèle contre les cotes de clôture : c'est le vrai test pour savoir s'il peut battre le marché.
5. Ajouter Serie A et Bundesliga.
