"""Normalisation des noms d'équipes entre les différentes sources de données."""
import unicodedata

LEAGUES = {
    "fr1": {"name": "Ligue 1", "country": "France", "flag": "🇫🇷", "of": "fr.1"},
    "en1": {"name": "Premier League", "country": "Angleterre", "flag": "🏴", "of": "en.1"},
    "es1": {"name": "LaLiga", "country": "Espagne", "flag": "🇪🇸", "of": "es.1"},
    "it1": {"name": "Serie A", "country": "Italie", "flag": "🇮🇹", "of": "it.1"},
}

# nom canonique -> variantes rencontrées (openfootball, vavel, Sportradar, API-Football, Understat)
# Si l'API renvoie un nom inconnu, update.py s'arrête avec « nom d'équipe inconnu » :
# il suffit d'ajouter ce nom dans la liste de l'équipe concernée ci-dessous.
ALIASES = {
    "fr1": {
        "PSG": ["Paris Saint-Germain FC", "Paris Saint Germain", "Paris Saint-Germain"],
        "Lille": ["Lille OSC", "LOSC Lille"],
        "Paris FC": ["Paris FC", "Paris"],
        "Marseille": ["Olympique de Marseille", "Olympique Marseille"],
        "Lyon": ["Olympique Lyonnais", "Olympique Lyon"],
        "Nice": ["OGC Nice", "Nice"],
        "Monaco": ["AS Monaco FC", "AS Monaco", "Monaco"],
        "Rennes": ["Stade Rennais FC 1901", "Stade Rennais FC", "Rennes", "Stade Rennais"],
        "Brest": ["Stade Brestois 29", "Stade Brest 29", "Brest", "Stade Brestois"],
        "Lorient": ["FC Lorient", "Lorient"],
        "Lens": ["Racing Club de Lens", "Racing Club De Lens", "RC Lens", "Lens"],
        "Toulouse": ["Toulouse FC", "Toulouse"],
        "Strasbourg": ["RC Strasbourg Alsace", "Strasbourg Alsace", "Strasbourg", "RC Strasbourg"],
        "Auxerre": ["AJ Auxerre", "Auxerre"],
        "Le Mans": ["Le Mans FC", "Le Mans"],
        "Angers": ["Angers SCO", "Angers"],
        "Troyes": ["ESTAC Troyes", "Troyes", "ES Troyes AC"],
        "Le Havre": ["Le Havre AC", "Le Havre"],
        "Saint-Étienne": ["AS Saint-Étienne"],
        "Metz": ["FC Metz"],
        "Nantes": ["FC Nantes"],
        "Montpellier": ["Montpellier HSC"],
        "Reims": ["Stade de Reims"],
        "Ajaccio": ["AC Ajaccio"],                              # Understat : Ajaccio
        "Clermont": ["Clermont Foot 63", "Clermont Foot"],      # Understat : Clermont Foot
    },
    "en1": {
        "Arsenal": ["Arsenal FC", "Arsenal"],
        "Brighton": ["Brighton & Hove Albion FC", "Brighton & Hove Albion"],
        "Man City": ["Manchester City FC", "Manchester City"],
        "Liverpool": ["Liverpool FC", "Liverpool"],
        "Chelsea": ["Chelsea FC", "Chelsea"],
        "Everton": ["Everton FC", "Everton"],
        "Bournemouth": ["AFC Bournemouth"],
        "Brentford": ["Brentford FC", "Brentford"],
        "Leeds": ["Leeds United FC", "Leeds United"],
        "Aston Villa": ["Aston Villa FC", "Aston Villa"],
        "Tottenham": ["Tottenham Hotspur FC", "Tottenham Hotspur"],
        "Newcastle": ["Newcastle United FC", "Newcastle United"],
        "Hull": ["Hull City AFC", "Hull City"],
        "Ipswich": ["Ipswich Town FC", "Ipswich Town"],
        "Fulham": ["Fulham FC", "Fulham"],
        "Nottingham Forest": ["Nottingham Forest FC", "Nottingham Forest"],
        "Coventry": ["Coventry City FC", "Coventry City"],
        "Man United": ["Manchester United FC", "Manchester United"],
        "Sunderland": ["Sunderland AFC", "Sunderland"],
        "Crystal Palace": ["Crystal Palace FC", "Crystal Palace"],
        "Burnley": ["Burnley FC"],
        "Leicester": ["Leicester City FC"],
        "Southampton": ["Southampton FC"],
        "West Ham": ["West Ham United FC"],
        "Wolves": ["Wolverhampton Wanderers FC", "Wolverhampton Wanderers"],   # Understat : Wolverhampton Wanderers
        "Luton": ["Luton Town FC", "Luton Town"],                             # Understat : Luton
        "Sheffield United": ["Sheffield United FC"],
    },
    "es1": {
        "Barcelone": ["FC Barcelona", "Barcelona"],
        "Real Madrid": ["Real Madrid CF", "Real Madrid"],
        "Atlético Madrid": ["Club Atlético de Madrid", "Atlético de Madrid", "Atletico Madrid"],
        "Betis": ["Real Betis Balompié", "Real Betis", "Real Betis Seville"],
        "Real Sociedad": ["Real Sociedad de Fútbol", "Real Sociedad", "Real Sociedad San Sebastian"],
        "Séville": ["Sevilla FC", "Sevilla"],
        "Athletic Bilbao": ["Athletic Club", "Athletic Bilbao"],
        "Villarreal": ["Villarreal CF", "Villarreal"],
        "La Corogne": ["Deportivo A Coruña", "RC Deportivo de A Coruna", "RC Deportivo La Coruña", "Deportivo La Coruna"],
        "Racing Santander": ["Racing Santander", "Real Racing Club", "Real Racing Club de Santander"],
        "Celta Vigo": ["RC Celta de Vigo", "Celta de Vigo"],
        "Alavés": ["Deportivo Alavés", "Deportivo Alaves"],
        "Espanyol": ["RCD Espanyol de Barcelona", "Espanyol", "Espanyol Barcelona"],
        "Rayo Vallecano": ["Rayo Vallecano de Madrid", "Rayo Vallecano"],
        "Getafe": ["Getafe CF", "Getafe"],
        "Osasuna": ["CA Osasuna", "Osasuna"],
        "Levante": ["Levante UD", "Levante"],
        "Elche": ["Elche CF", "Elche"],
        "Valence": ["Valencia CF", "Valencia"],
        "Málaga": ["Málaga CF", "Malaga CF", "Málaga"],
        "Leganés": ["CD Leganés"],
        "Girona": ["Girona FC"],
        "Majorque": ["RCD Mallorca", "Mallorca"],                 # Understat : Mallorca
        "Oviedo": ["Real Oviedo"],
        "Valladolid": ["Real Valladolid CF", "Real Valladolid"],  # Understat : Real Valladolid
        "Las Palmas": ["UD Las Palmas"],
        "Almería": ["UD Almería", "Almeria"],                     # Understat : Almeria
        "Cadix": ["Cádiz CF", "Cadiz"],                           # Understat : Cadiz
        "Grenade": ["Granada CF", "Granada"],                     # Understat : Granada
    },
    "it1": {
        "Inter": ["FC Internazionale Milano", "Internazionale", "Inter Milan", "Inter Milano", "FC Inter"],
        "AC Milan": ["Milan", "AC Milano", "Milan AC"],
        "Juventus": ["Juventus FC", "Juventus Turin"],
        "Naples": ["SSC Napoli", "Napoli", "SSC Naples"],
        "AS Rome": ["AS Roma", "Roma"],
        "Lazio": ["SS Lazio", "Lazio Rome", "Lazio Roma"],
        "Atalanta": ["Atalanta BC", "Atalanta Bergamo", "Atalanta Bergamasca Calcio"],
        "Fiorentina": ["ACF Fiorentina"],
        "Bologne": ["Bologna FC 1909", "Bologna", "Bologna FC"],
        "Torino": ["Torino FC"],
        "Genoa": ["Genoa CFC", "Genoa CFC 1893"],
        "Sassuolo": ["US Sassuolo Calcio", "US Sassuolo"],
        "Udinese": ["Udinese Calcio"],
        "Lecce": ["US Lecce"],
        "Cagliari": ["Cagliari Calcio"],
        "Vérone": ["Hellas Verona FC", "Hellas Verona", "Verona"],
        "Empoli": ["Empoli FC"],
        "Monza": ["AC Monza"],
        "Parme": ["Parma Calcio 1913", "Parma", "Parma Calcio"],
        "Côme": ["Como 1907", "Como"],
        "Venise": ["Venezia FC", "Venezia"],
        "Cremonese": ["US Cremonese"],
        "Pise": ["AC Pisa 1909", "Pisa", "Pisa SC", "AC Pisa"],
        "Salernitana": ["US Salernitana 1919", "US Salernitana"],
        "Sampdoria": ["UC Sampdoria"],
        "Spezia": ["Spezia Calcio"],
        "Frosinone": ["Frosinone Calcio"],
    },
}


def _key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("-", " ").split())


_LOOKUP = {
    lg: {_key(v): canon for canon, vs in table.items() for v in vs + [canon]}
    for lg, table in ALIASES.items()
}


UNKNOWN: set = set()


def canon(league: str, name: str, strict: bool = True) -> str:
    k = _key(name)
    if k in _LOOKUP[league]:
        return _LOOKUP[league][k]
    if strict:
        raise KeyError(f"[{league}] nom d'équipe inconnu : {name!r}")
    # équipe uniquement présente dans l'historique : on garde son nom
    UNKNOWN.add((league, name))
    return name
