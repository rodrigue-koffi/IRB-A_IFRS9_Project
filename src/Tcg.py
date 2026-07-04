"""
Tcg.py
Etape 3 : construction de la chronologie du portefeuille.

Le jeu de donnees source ne contient aucune date. Ce module construit :

  A) Un PANEL D'OBSERVATIONS ANNUELLES par dossier (buildAnnualPerformancePanel),
     conforme a la pratique EBA GL/2017/16 : chaque dossier est observe a
     PLUSIEURS reprises au cours de sa vie (t0=origination, t0+12m, t0+24m,
     ...), et a CHAQUE point on regarde s'il fait defaut dans les 12 mois qui
     suivent CE point precis. Un pret origine en 2011 qui fait defaut en 2014
     n'est PAS capture par une fenetre a l'octroi seule (2011->2012) : il
     apparait comme non-evenement aux observations 2011 et 2012, puis comme
     evenement de defaut a l'observation 2013 (fenetre 2013->2014). C'est ce
     panel qui alimente la calibration LRA (pdCalibration.py).

  B) Le STATUT DU LIVRE A LA DATE D'ARRETE (ACTIVE / DEFAULTED / MATURED),
     utilise par le staging IFRS9 (ifrs9Staging.py) : photographie a un
     instant T du livre courant, sans rapport avec le panel historique de
     calibration.

Regles de construction du panel (pour eviter tout biais) :
  - Une fenetre qui n'est pas encore ENTIEREMENT REALISEE a la date d'arrete
    (observationDate + 12 mois > OBSERVATION_DATE) est exclue : on ne
    calibre jamais sur un resultat qui ne serait pas observable en
    production a la date du jour (pas de fuite d'information/look-ahead).
  - Une fenetre CENSUREE par l'echeance du credit (le pret est solde avant
    la fin des 12 mois, sans avoir fait defaut) est exclue plutot que
    comptee comme un "non-defaut" : on ne sait pas ce qui se serait passe.
  - Des qu'un defaut est detecte dans une fenetre, le dossier sort de la
    population "vivante" (pas d'observation ulterieure pour ce dossier).
"""

import numpy as np
import pandas as pd
from src import config

MAX_OBSERVATIONS_PER_LOAN = 10


def assignVintageYears(portfolioFrame, randomState):
    """Repartit les dossiers sur les millesimes d'octroi, pondere vers les annees recentes
    (pyramide des ages realiste : les vieux millesimes ont deja largement solde)."""
    portfolioFrame = portfolioFrame.copy()
    vintageYears = np.arange(config.VINTAGE_YEAR_MIN, config.VINTAGE_YEAR_MAX + 1)
    productionWeights = np.linspace(0.6, 2.2, len(vintageYears))
    productionWeights = productionWeights / productionWeights.sum()
    portfolioFrame["vintageYear"] = randomState.choice(vintageYears, size=len(portfolioFrame), p=productionWeights)
    return portfolioFrame


def buildOriginationAndMaturityDates(portfolioFrame, randomState):
    portfolioFrame = portfolioFrame.copy()
    dayOffsets = randomState.integers(0, 365, size=len(portfolioFrame))
    portfolioFrame["originationDate"] = pd.to_datetime(
        portfolioFrame["vintageYear"].astype(str) + "-01-01"
    ) + pd.to_timedelta(dayOffsets, unit="D")

    portfolioFrame["maturityDate"] = portfolioFrame["originationDate"] + pd.to_timedelta(
        (portfolioFrame["durationMonths"] * 30.44).round(0), unit="D"
    )
    return portfolioFrame


def simulateDefaultDates(portfolioFrame, randomState):
    """Pour chaque dossier en defaut (defaultEverFlag==1), tire UNE date de defaut
    plausible dans (originationDate, maturityDate]. Cette date unique sera ensuite
    testee contre PLUSIEURS fenetres annuelles dans buildAnnualPerformancePanel."""
    portfolioFrame = portfolioFrame.copy()
    defaultDates = pd.Series(pd.NaT, index=portfolioFrame.index, dtype="datetime64[ns]")

    defaultedIndex = portfolioFrame.index[portfolioFrame["defaultEverFlag"] == 1]
    for idx in defaultedIndex:
        row = portfolioFrame.loc[idx]
        totalContractDays = max((row["maturityDate"] - row["originationDate"]).days, 60)

        isDownturnVintage = int(row["vintageYear"]) in config.DOWNTURN_YEARS
        skewParameter = 1.6 if isDownturnVintage else 2.6
        fractionOfLife = randomState.random() ** skewParameter
        offsetDays = int(np.clip(fractionOfLife * totalContractDays, 30, totalContractDays))

        defaultDates.loc[idx] = row["originationDate"] + pd.Timedelta(days=offsetDays)

    portfolioFrame["defaultDate"] = defaultDates
    return portfolioFrame


def computeFirstYearDefaultFlag(portfolioFrame):
    """
    Indicateur DIAGNOSTIC uniquement (PAS use pour la calibration LRA,
    volontairement isole pour eviter toute confusion avec le panel) :
    1 si le defaut simule survient dans les 12 premiers mois de vie du credit.
    Utile pour comparer, en reporting, la part de defauts "precoces" vs
    "tardifs", mais ne doit jamais servir seul a estimer une PD de portefeuille.
    """
    portfolioFrame = portfolioFrame.copy()
    performanceHorizon = portfolioFrame["originationDate"] + pd.DateOffset(months=config.PERFORMANCE_WINDOW_MONTHS)
    hasDefaultDate = portfolioFrame["defaultDate"].notna()
    withinFirstYear = (portfolioFrame["defaultDate"] > portfolioFrame["originationDate"]) & (
        portfolioFrame["defaultDate"] <= performanceHorizon
    )
    portfolioFrame["firstYearDefaultFlag"] = (hasDefaultDate & withinFirstYear).astype(int)
    return portfolioFrame


def buildAnnualPerformancePanel(portfolioFrame, maxObservationsPerLoan=MAX_OBSERVATIONS_PER_LOAN):
    """
    Construit le panel (obligorId, observationDate, performanceYear, default12mFlag)
    utilise pour la calibration LRA. Voir docstring du module pour la logique complete.
    """
    observationDate = pd.Timestamp(config.OBSERVATION_DATE)
    records = []

    requiredColumns = portfolioFrame[["obligorId", "originationDate", "maturityDate", "defaultDate"]]
    for row in requiredColumns.itertuples(index=False):
        t = row.originationDate
        maturity = row.maturityDate
        defaultDate = row.defaultDate

        for _ in range(maxObservationsPerLoan):
            if t >= maturity:
                break  # credit deja solde a ce point : plus d'observation possible

            windowEnd = t + pd.DateOffset(months=config.PERFORMANCE_WINDOW_MONTHS)

            if windowEnd > observationDate:
                break  # fenetre pas encore entierement realisee -> pas de look-ahead

            defaultedInWindow = pd.notna(defaultDate) and (t < defaultDate <= windowEnd)

            if defaultedInWindow:
                records.append((row.obligorId, t, t.year, 1))
                break  # le dossier sort de la population vivante

            if maturity < windowEnd:
                break  # fenetre censuree par l'echeance -> exclue (pas comptee comme non-defaut)

            records.append((row.obligorId, t, t.year, 0))
            t = windowEnd  # anniversaire suivant

    performancePanel = pd.DataFrame(
        records, columns=["obligorId", "observationDate", "performanceYear", "default12mFlag"]
    )
    return performancePanel


def computeBookStatusAtObservationDate(portfolioFrame):
    """
    Photographie du portefeuille a la date d'arrete (config.OBSERVATION_DATE),
    utilisee par le staging IFRS9 :
      - DEFAULTED : defautDate <= observationDate            -> Stage 3 direct
      - ACTIVE    : originationDate <= observationDate < maturityDate, sans defaut -> Stage 1/2
      - MATURED   : credit deja arrive a echeance sans defaut -> hors perimetre ECL
      - FUTURE    : credit pas encore origine a l'arrete       -> hors perimetre ECL
    """
    portfolioFrame = portfolioFrame.copy()
    observationDate = pd.Timestamp(config.OBSERVATION_DATE)

    hasDefaulted = portfolioFrame["defaultDate"].notna() & (portfolioFrame["defaultDate"] <= observationDate)
    notYetOriginated = portfolioFrame["originationDate"] > observationDate
    alreadyMatured = (~hasDefaulted) & (portfolioFrame["maturityDate"] <= observationDate)

    status = np.select(
        [hasDefaulted, notYetOriginated, alreadyMatured],
        ["DEFAULTED", "FUTURE", "MATURED"],
        default="ACTIVE",
    )
    portfolioFrame["bookStatusAsOfObservationDate"] = status

    monthsOnBook = (observationDate - portfolioFrame["originationDate"]).dt.days / 30.44
    portfolioFrame["monthsOnBookAtObservation"] = monthsOnBook.clip(lower=0)
    return portfolioFrame


def simulateDaysPastDue(portfolioFrame, randomState):
    """Proxy d'arrieres de paiement a la date d'arrete (backstop SICR 30 jours, IFRS9)."""
    portfolioFrame = portfolioFrame.copy()
    observationDate = pd.Timestamp(config.OBSERVATION_DATE)

    baseArrears = randomState.poisson(lam=1.2, size=len(portfolioFrame))
    monthsToDefault = (portfolioFrame["defaultDate"] - observationDate).dt.days / 30.44
    closeToFutureDefault = monthsToDefault.between(0, 6)
    arrearsBoost = np.where(
        closeToFutureDefault.fillna(False), randomState.integers(20, 75, size=len(portfolioFrame)), 0
    )

    daysPastDue = np.clip(baseArrears + arrearsBoost, 0, 180)
    isRelevant = portfolioFrame["bookStatusAsOfObservationDate"].isin(["ACTIVE", "DEFAULTED"])
    portfolioFrame["daysPastDue"] = np.where(isRelevant, daysPastDue, 0)
    return portfolioFrame


def runTemporalChronologyGeneration(portfolioFrame):
    print("=" * 80)
    print("ETAPE 3 - GENERATION DE LA CHRONOLOGIE (OCTROI / DEFAUT / ARRETE / PANEL LRA)")
    print("=" * 80)

    randomState = np.random.default_rng(config.RANDOM_SEED + 1)

    portfolioFrame = assignVintageYears(portfolioFrame, randomState)
    portfolioFrame = buildOriginationAndMaturityDates(portfolioFrame, randomState)
    portfolioFrame = simulateDefaultDates(portfolioFrame, randomState)
    portfolioFrame = computeFirstYearDefaultFlag(portfolioFrame)
    portfolioFrame = computeBookStatusAtObservationDate(portfolioFrame)
    portfolioFrame = simulateDaysPastDue(portfolioFrame, randomState)

    performancePanel = buildAnnualPerformancePanel(portfolioFrame)

    print(f"[Tcg] Date d'arrete du portefeuille : {config.OBSERVATION_DATE}")
    print(f"[Tcg] Taux de defaut 1ere annee (diagnostic uniquement) : "
          f"{portfolioFrame['firstYearDefaultFlag'].mean():.2%}")
    print(f"[Tcg] Panel LRA : {len(performancePanel)} observations "
          f"annuelles sur {performancePanel['obligorId'].nunique()} dossiers "
          f"({performancePanel['performanceYear'].min()}-{performancePanel['performanceYear'].max()})")
    print(f"[Tcg] Taux de defaut annuel moyen (panel multi-observations) : "
          f"{performancePanel['default12mFlag'].mean():.2%}")
    print("[Tcg] Statuts a l'arrete :")
    print(portfolioFrame["bookStatusAsOfObservationDate"].value_counts().to_string())

    return portfolioFrame, performancePanel
