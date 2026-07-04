"""
ifrs9Staging.py


Etape 10: bascule de la PD Through-The-Cycle (pdFinalRegulatory,
utilisee pour le capital reglementaire IRB) vers une PD Point-In-Time (PIT),
seule pertinente pour l'IFRS 9 (par. 5.5 IFRS 9 - mesure de l'ECL a chaque
date de reporting sur la base des conditions actuelles et previsionnelles).

La PD PIT combine :
  1. Un choc macroeconomique systemique (ecart de la conjoncture actuelle a
     la moyenne de long terme, meme logique que le script original mais
     applique proprement a la date d'ARRETE ).
  2. Un signal idiosyncratique comportemental : les arrieres de paiement
     (daysPastDue) generes dans Tcg.py.

Le SICR (Significant Increase in Credit Risk, par. 5.5.9 IFRS 9) est ensuite
detecte par un faisceau de 3 indices, comme l'exige la pratique de place
(EBA GL/2016/07) :
  - augmentation relative de la PD depuis l'octroi
  - augmentation absolue de la PD depuis l'octroi
  - backstop des 30 jours d'arrieres (par. 5.5.11 IFRS 9)

Staging :
  Stage 1 : encours sain, ECL a 12 mois
  Stage 2 : SICR averee, ECL a maturite (lifetime)
  Stage 3 : deja en defaut a l'arrete, ECL a maturite (lifetime)
Seuls les dossiers ACTIVE ou DEFAULTED a la date d'arrete sont notes
(un credit deja solde -> MATURED -> hors perimetre ECL).
"""

import numpy as np
import pandas as pd
from src import config

# Serie macro simplifiee (proxy taux de chomage), pour la composante
# systemique de la PD PIT. Les annees de choc (config.DOWNTURN_YEARS)
# affichent un pic, coherent avec la generation des dates de defaut.
MACRO_YEARS = np.arange(config.VINTAGE_YEAR_MIN, 2026)
MACRO_UNEMPLOYMENT_RATE = {
    year: (9.5 if year in config.DOWNTURN_YEARS else 7.0 - 0.15 * (year - config.VINTAGE_YEAR_MIN))
    for year in MACRO_YEARS
}
PIT_SENSITIVITY_BETA = 0.6


def computePdAtOrigination(portfolioFrame):
    """PD a l'octroi = PD finale reglementaire du grade (LRA + MoC), figee au moment de la notation initiale."""
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["pdOriginationGrade"] = portfolioFrame["pdFinalRegulatory"]
    return portfolioFrame


def computePdPointInTime(portfolioFrame):
    """Ajuste la PD d'octroi par un choc macro (annee d'arrete) et un signal d'arrieres."""
    portfolioFrame = portfolioFrame.copy()
    observationYear = pd.Timestamp(config.OBSERVATION_DATE).year

    meanUnemployment = np.mean(list(MACRO_UNEMPLOYMENT_RATE.values()))
    stdUnemployment = np.std(list(MACRO_UNEMPLOYMENT_RATE.values()))
    currentUnemployment = MACRO_UNEMPLOYMENT_RATE.get(observationYear, meanUnemployment)
    deltaMacro = (currentUnemployment - meanUnemployment) / stdUnemployment

    macroMultiplier = np.exp(PIT_SENSITIVITY_BETA * deltaMacro)

    # Signal comportemental : chaque tranche de 10 jours d'arrieres majore la PD de 15%,
    # avec un saut supplementaire au-dela du backstop de 30 jours. cette hyp tient ou pas
    arrearsMultiplier = 1 + 0.015 * portfolioFrame["daysPastDue"]
    backstopMultiplier = np.where(portfolioFrame["daysPastDue"] >= config.SICR_BACKSTOP_DAYS_PAST_DUE, 1.5, 1.0)

    portfolioFrame["pdCurrentPit"] = (
        portfolioFrame["pdOriginationGrade"] * macroMultiplier * arrearsMultiplier * backstopMultiplier
    ).clip(0.0003, 0.999)
    return portfolioFrame


def computeLifetimePd(portfolioFrame):
    """PD a maturite (approximation actuarielle standard : 1-(1-PD12m)^n)."""
    portfolioFrame = portfolioFrame.copy()
    observationDate = pd.Timestamp(config.OBSERVATION_DATE)
    remainingMonths = ((portfolioFrame["maturityDate"] - observationDate).dt.days / 30.44).clip(lower=1)
    portfolioFrame["remainingMonths"] = remainingMonths

    portfolioFrame["pdLifetime"] = (
        1 - (1 - portfolioFrame["pdCurrentPit"]) ** (remainingMonths / 12)
    ).clip(0.0003, 0.999)
    return portfolioFrame


def detectSicr(portfolioFrame):
    portfolioFrame = portfolioFrame.copy()
    relativeIncrease = portfolioFrame["pdCurrentPit"] / portfolioFrame["pdOriginationGrade"].replace(0, np.nan)
    absoluteIncrease = portfolioFrame["pdCurrentPit"] - portfolioFrame["pdOriginationGrade"]

    portfolioFrame["sicrTriggerRelative"] = relativeIncrease >= config.SICR_RELATIVE_PD_MULTIPLE
    portfolioFrame["sicrTriggerAbsolute"] = absoluteIncrease >= config.SICR_ABSOLUTE_PD_DELTA
    portfolioFrame["sicrTriggerBackstop"] = portfolioFrame["daysPastDue"] >= config.SICR_BACKSTOP_DAYS_PAST_DUE

    portfolioFrame["sicrFlag"] = (
        portfolioFrame["sicrTriggerRelative"].fillna(False)
        | portfolioFrame["sicrTriggerAbsolute"].fillna(False)
        | portfolioFrame["sicrTriggerBackstop"].fillna(False)
    )
    return portfolioFrame


def assignIfrs9Stage(portfolioFrame):
    portfolioFrame = portfolioFrame.copy()

    def stageForRow(row):
        if row["bookStatusAsOfObservationDate"] not in ("ACTIVE", "DEFAULTED"):
            return np.nan
        if row["bookStatusAsOfObservationDate"] == "DEFAULTED":
            return 3
        return 2 if row["sicrFlag"] else 1

    portfolioFrame["ifrs9Stage"] = portfolioFrame.apply(stageForRow, axis=1)
    return portfolioFrame


def computeEclByStage(portfolioFrame):
    """
    Actualisation simplifiee au taux effectif proxy (config.RECOVERY_DISCOUNT_RATE_ANNUAL),
    convention de mi-periode (t = horizon / 2) : approximation standard quand
    l'echeancier contractuel detaille n'est pas disponible selon mes rechercjes ( Valide?).
    """
    portfolioFrame = portfolioFrame.copy()
    discountRate = config.RECOVERY_DISCOUNT_RATE_ANNUAL

    discountFactor12m = 1 / (1 + discountRate) ** 0.5
    discountFactorLifetime = 1 / (1 + discountRate) ** (portfolioFrame["remainingMonths"] / 12 / 2)

    ecl12mRaw = portfolioFrame["pdCurrentPit"] * portfolioFrame["lgdDownturnEstimate"] * portfolioFrame["eadFinal"] * discountFactor12m
    eclLifetimeRaw = portfolioFrame["pdLifetime"] * portfolioFrame["lgdDownturnEstimate"] * portfolioFrame["eadFinal"] * discountFactorLifetime

    portfolioFrame["ecl12Month"] = np.where(portfolioFrame["ifrs9Stage"] == 1, ecl12mRaw, 0.0)
    portfolioFrame["eclLifetime"] = np.where(portfolioFrame["ifrs9Stage"].isin([2, 3]), eclLifetimeRaw, 0.0)
    portfolioFrame["eclFinal"] = np.where(
        portfolioFrame["ifrs9Stage"].notna(), portfolioFrame["ecl12Month"] + portfolioFrame["eclLifetime"], np.nan
    )
    return portfolioFrame


def runIfrs9Staging(portfolioFrame):
    print("/" * 20)
    print("ETAPE 10 - STAGING IFRS 9 (PD PIT, SICR MULTI-CRITERES, ECL)")
    print("/" * 15)

    portfolioFrame = computePdAtOrigination(portfolioFrame)
    portfolioFrame = computePdPointInTime(portfolioFrame)
    portfolioFrame = computeLifetimePd(portfolioFrame)
    portfolioFrame = detectSicr(portfolioFrame)
    portfolioFrame = assignIfrs9Stage(portfolioFrame)
    portfolioFrame = computeEclByStage(portfolioFrame)

    ratedBook = portfolioFrame[portfolioFrame["ifrs9Stage"].notna()]
    print(f"[ifrs9Staging] Perimetre note (ACTIVE + DEFAULTED) : {len(ratedBook)} / {len(portfolioFrame)} dossiers")
    print(ratedBook["ifrs9Stage"].value_counts().sort_index().to_string())
    print(f"[ifrs9Staging] ECL totale IFRS9 : {ratedBook['eclFinal'].sum():,.0f}")

    return portfolioFrame
