"""
eadEstimation.py
=================
Etape 9 /: Exposition Au Defaut. Les credits du jeu de
donnees sont des prets amortissables classiques (pas de ligne renouvelable) :
l'EAD est donc principalement le capital restant du a la date d'arrete. Le
segment PME/Corporate se voit neanmoins attribuer une petite quote-part de
ligne hors bilan (proxy decouvert professionnel), ce qui permet d'illustrer
le Facteur de Conversion en Credit (CCF, Art. 166 CRR) plutot que de
l'appliquer uniformement comme dans les version précédante.
"""

import numpy as np
import pandas as pd
from src import config

# CCF indicatifs par objet du financement (proxy pedagogique, a rapprocher
# en production des valeurs supervisees Art. 166 CRR pour la methode F-IRB,
# ou des CCF internes valides pour la methode A-IRB).
CCF_BY_PURPOSE = {
    "car": 0.20,
    "radio/TV": 0.10,
    "furniture/equipment": 0.20,
    "business": 0.45,
    "education": 0.10,
    "repairs": 0.20,
    "domestic appliances": 0.10,
    "vacation/others": 0.15,
}
DEFAULT_CCF = 0.20


def computeOutstandingBalanceAtObservation(portfolioFrame):
    """
    Amortissement lineaire simplifie du capital restant du entre
    originationDate et la date d'arrete (ou la date de defaut si anterieure).
    """
    portfolioFrame = portfolioFrame.copy()
    observationDate = pd.Timestamp(config.OBSERVATION_DATE)

    referenceDate = portfolioFrame["defaultDate"].fillna(observationDate).clip(upper=observationDate)
    monthsElapsed = ((referenceDate - portfolioFrame["originationDate"]).dt.days / 30.44).clip(lower=0)
    amortizedFraction = (monthsElapsed / portfolioFrame["durationMonths"].clip(lower=1)).clip(0, 1)

    portfolioFrame["onBalanceExposure"] = portfolioFrame["creditAmount"] * (1 - amortizedFraction)
    return portfolioFrame


def computeOffBalanceCommitment(portfolioFrame, randomState):
    """Ligne hors bilan (proxy decouvert professionnel), uniquement PME/Corporate."""
    portfolioFrame = portfolioFrame.copy()
    isSmeLike = portfolioFrame["perimeterSegment"].isin(["RETAIL_SME", "CORPORATE_SME"])
    offBalance = np.zeros(len(portfolioFrame))
    if isSmeLike.sum() > 0:
        offBalance[isSmeLike.values] = portfolioFrame.loc[isSmeLike, "creditAmount"] * randomState.uniform(
            0.10, 0.30, size=int(isSmeLike.sum())
        )
    portfolioFrame["offBalanceCommitment"] = offBalance
    return portfolioFrame


def applyCcfAndComputeEad(portfolioFrame):
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["ccfAssigned"] = portfolioFrame["purpose"].map(CCF_BY_PURPOSE).fillna(DEFAULT_CCF)
    portfolioFrame["eadFinal"] = (
        portfolioFrame["onBalanceExposure"] + portfolioFrame["ccfAssigned"] * portfolioFrame["offBalanceCommitment"]
    ).clip(lower=0)
    return portfolioFrame


def runEadEstimation(portfolioFrame):
    print("$" * 15)
    print("ETAPE 9 - EXPOSITION AU DEFAUT (AMORTISSEMENT + CCF SUR HORS BILAN PME)")
    print("$" * 15)

    randomState = np.random.default_rng(config.RANDOM_SEED + 3)

    portfolioFrame = computeOutstandingBalanceAtObservation(portfolioFrame)
    portfolioFrame = computeOffBalanceCommitment(portfolioFrame, randomState)
    portfolioFrame = applyCcfAndComputeEad(portfolioFrame)

    print(f"[eadEstimation] EAD totale du portefeuille : {portfolioFrame['eadFinal'].sum():,.0f}")
    return portfolioFrame
