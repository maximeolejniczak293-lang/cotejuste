# Snapshot récupéré le 13/11/2026 (source : flux Sportradar) — classements + prochains matchs + probas Sportradar
#
# Depuis le passage à API-Football :
#  - STANDINGS sert de classement officiel de référence pour data.py (le plan gratuit de l'API ne fournit
#    pas le classement 2026). Pour revérifier plus tard, recopie le classement officiel (V, N, D, points)
#    et change SNAPSHOT_DATE : seuls les matchs joués jusqu'à cette date sont comparés.
#  - FIXTURES n'est plus utilisé (les matchs à venir viennent de l'API et du calendrier openfootball).
SNAPSHOT_DATE = "2026-11-13"
# Matchs reportés connus, pas encore rejoués : (domicile, extérieur) avec les noms de names.py.
# Ils ne comptent pas comme « résultat manquant » tant que l'API ne les a pas reprogrammés à une date passée.
REPORTES = {
    "es1": [("Rayo Vallecano", "Athletic Bilbao")],  # journée 8, prévu le 10/10/2026
}
STANDINGS = {
 "fr1": [("Paris Saint-Germain",7,2,1,23),("Lille OSC",6,3,1,21),("Paris FC",6,2,2,20),("Olympique Marseille",6,0,4,18),("Olympique Lyon",5,2,3,17),("OGC Nice",5,2,3,17),("AS Monaco",4,4,2,16),("Stade Rennais FC",5,1,4,16),("Stade Brest 29",4,3,3,15),("FC Lorient",4,3,3,15),("Racing Club De Lens",4,1,5,13),("Toulouse FC",3,4,3,13),("Strasbourg Alsace",3,1,6,10),("AJ Auxerre",3,1,6,10),("Le Mans FC",1,5,4,8),("Angers SCO",2,2,6,8),("ESTAC Troyes",2,2,6,8),("Le Havre AC",0,2,8,2)],
 "en1": [("Arsenal FC",9,0,1,27),("Brighton & Hove Albion",7,1,2,22),("Manchester City",7,0,3,21),("Liverpool FC",5,3,2,18),("Chelsea FC",5,1,4,16),("Everton FC",4,4,2,16),("AFC Bournemouth",4,3,3,15),("Brentford FC",3,5,2,14),("Leeds United",3,5,2,14),("Aston Villa",3,4,3,13),("Tottenham Hotspur",3,3,4,12),("Newcastle United",3,3,4,12),("Hull City",2,5,3,11),("Ipswich Town",3,2,5,11),("Fulham FC",2,4,4,10),("Nottingham Forest",2,3,5,9),("Coventry City",3,0,7,9),("Manchester United",1,5,4,8),("Sunderland AFC",2,2,6,8),("Crystal Palace",2,1,7,7)],
 "es1": [("FC Barcelona",11,0,1,33),("Real Madrid",10,0,2,30),("Atletico Madrid",9,1,2,28),("Real Betis Seville",8,2,2,26),("Real Sociedad San Sebastian",7,1,4,22),("Sevilla FC",5,3,4,18),("Athletic Bilbao",4,4,3,16),("Villarreal CF",4,3,5,15),("RC Deportivo de A Coruna",3,6,3,15),("Racing Santander",4,2,6,14),("RC Celta de Vigo",2,7,3,13),("Deportivo Alaves",3,4,5,13),("Espanyol Barcelona",3,3,6,12),("Rayo Vallecano",3,3,5,12),("Getafe CF",3,3,6,12),("CA Osasuna",3,3,6,12),("Levante UD",2,5,5,11),("Elche CF",2,4,6,10),("Valencia CF",2,3,7,9),("Malaga CF",0,5,7,5)],
}
# (date ISO UTC, domicile, extérieur, p_dom, p_nul, p_ext)  — probabilités Sportradar en %
FIXTURES = {
 "fr1": [("2026-11-20T19:45:00Z","ESTAC Troyes","Le Havre AC",46.3,26.7,27.0),("2026-11-21T16:15:00Z","OGC Nice","Paris Saint-Germain",15.6,18.2,66.2),("2026-11-21T19:45:00Z","Racing Club De Lens","Toulouse FC",51.1,24.3,24.6),("2026-11-21T19:45:00Z","Lille OSC","Olympique Lyon",40.3,28.6,31.1),("2026-11-21T19:45:00Z","AS Monaco","AJ Auxerre",68.8,18.3,12.9),("2026-11-21T19:45:00Z","Strasbourg Alsace","Stade Brest 29",43.2,25.3,31.5),("2026-11-22T14:00:00Z","Paris FC","Angers SCO",70.8,18.0,11.2),("2026-11-22T16:15:00Z","FC Lorient","Stade Rennais FC",33.6,27.0,39.4),("2026-11-22T19:45:00Z","Olympique Marseille","Le Mans FC",69.3,17.7,13.0)],
 "en1": [("2026-11-21T12:30:00Z","Manchester City","Fulham FC",68.1,18.0,13.9),("2026-11-21T15:00:00Z","Aston Villa","Sunderland AFC",54.1,24.8,21.1),("2026-11-21T15:00:00Z","AFC Bournemouth","Nottingham Forest",47.0,26.6,26.4),("2026-11-21T15:00:00Z","Chelsea FC","Leeds United",50.9,25.2,23.9),("2026-11-21T15:00:00Z","Coventry City","Crystal Palace",40.4,26.3,33.3),("2026-11-21T15:00:00Z","Tottenham Hotspur","Ipswich Town",62.0,21.0,17.0),("2026-11-21T17:30:00Z","Newcastle United","Arsenal FC",17.2,22.1,60.7),("2026-11-22T14:00:00Z","Hull City","Brighton & Hove Albion",15.8,20.6,63.6),("2026-11-22T16:30:00Z","Liverpool FC","Manchester United",55.0,22.7,22.3),("2026-11-23T20:00:00Z","Brentford FC","Everton FC",46.1,26.2,27.7)],
 "es1": [("2026-11-20T20:00:00Z","Athletic Bilbao","Espanyol Barcelona",65.5,20.5,14.0),("2026-11-21T13:00:00Z","Deportivo Alaves","RC Deportivo de A Coruna",45.0,28.5,26.5),("2026-11-21T15:15:00Z","Rayo Vallecano","Valencia CF",48.4,27.4,24.2),("2026-11-21T17:30:00Z","Sevilla FC","Real Betis Seville",30.7,26.6,42.7),("2026-11-21T20:00:00Z","Real Madrid","RC Celta de Vigo",81.0,12.1,6.9),("2026-11-22T13:00:00Z","FC Barcelona","Villarreal CF",78.9,11.9,9.2),("2026-11-22T15:15:00Z","Racing Santander","Real Sociedad San Sebastian",30.7,24.4,44.9),("2026-11-22T17:30:00Z","CA Osasuna","Malaga CF",54.5,25.3,20.2),("2026-11-22T20:00:00Z","Getafe CF","Atletico Madrid",16.6,23.9,59.5),("2026-11-23T20:00:00Z","Levante UD","Elche CF",43.6,26.2,30.2)],
}
