"""Réglages de CoteJuste, regroupés ici (le seul fichier à modifier pour les ajuster)."""

# --- Probabilité finale = W_MODELE × modèle + (1 − W_MODELE) × marché (cotes moyennes, marge retirée)
W_MODELE = 0.5

# --- Ton bookmaker : quand l'API fournit sa cote pour un match, c'est la « cote prise » du bilan
#     (sinon la cote moyenne). Comparaison sans accents ni majuscules, sur une partie du nom.
BOOKMAKER = "Betclic"

# --- Recos du jour (matchs pas encore commencés, à moins de HORIZON_H heures, avec cotes)
HORIZON_H = 48
SECU = dict(p_min=0.65, cote_min=1.30, valeur_min=1.00)
VALEUR = dict(valeur_min_1n2=1.05, valeur_min_buts=1.08, p_min=0.35, marge_cote_min=1.05)
COMBI = dict(p_min=0.55, chance_min=0.30, valeur_min=1.00, tailles=(2, 3))
GROSSE = dict(cote_min=5.0, valeur_min=1.00, mise=1.0)
CONFIANCE_ECART = 0.05      # modèle et marché « d'accord » à 5 points près

# --- Mises (calculées dans la page, à partir de ta bankroll)
KELLY_FRACTION = 0.25
KELLY_PLAFOND = 0.05        # 5 % de la bankroll au plus par pari
MISE_MIN = 0.50
PLAFOND_TOTAL = 0.40        # total des mises conseillées <= 40 % de la bankroll

# --- Bilan
VALEUR_MIN_BILAN = 1.05     # « toutes les valeurs » : cote prise × proba >= 1,05
ECHANTILLON_MIN = 50        # sous 50 paris : « échantillon trop petit pour conclure »
W_MIN_MATCHS = 200          # matchs avec cote de clôture avant de calculer le meilleur W
