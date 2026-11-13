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

Jour sans match : 3 requêtes. Samedi matin chargé : environ 45 à 50, en gardant de quoi récupérer les compositions de la journée. Le garde-fou s'arrête à 90.

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
