"""
lgdEstimation.py
=================
Etape 8  : estimation de la LGD par methode "workout"
(recouvrement reel), et non par tirage aleatoire uniforme comme  dans ma v3.


La base source ne contient aucun flux de recouvrement ni cout de gestion du
contentieux : ce module les simule explicitement, ce qui permet d'appliquer
la vraie formule reglementaire de la LGD economique (Art. 181 CRR /
EBA GL/2019/03, par. 90-99) :

    LGD_realisee = 1 - [ VA(recouvrements) - couts_directs - couts_indirects ] / EAD_au_defaut

Le recouvrement est simule comme fonction :
  - du collateral proxy (type de logement, cf. featureEngineering.py)
  - du segment de perimetre (une PME/Corporate a generalement un
    recouvrement plus structure qu'un particulier)
  - d'un horizon de recouvrement aleatoire (mois), actualise au taux
    config.RECOVERY_DISCOUNT_RATE_ANNUAL (proxy de TIE)

Une LGD downturn (Art. 181(1)(b) CRR) est ensuite calculee : elle doit etre
au moins aussi conservatrice que la LGD moyenne sur les millesimes de choc
(config.DOWNTURN_YEARS).
"""

import numpy as np
import pandas as pd
from src import config


def simulateRecoveryComponents(portfolioFrame, randomState):
    """Simule montant recouvre, delai de recouvrement, couts directs/indirects pour les defauts."""
    portfolioFrame = portfolioFrame.copy()
    isDefaulted = portfolioFrame["defaultDate"].notna()
    nDefaulted = int(isDefaulted.sum())

    recoveryRate = np.full(len(portfolioFrame), np.nan)
    recoveryMonths = np.full(len(portfolioFrame), np.nan)
    directCost = np.full(len(portfolioFrame), np.nan)
    indirectCost = np.full(len(portfolioFrame), np.nan)

    if nDefaulted > 0:
        defaultedFrame = portfolioFrame.loc[isDefaulted]

        # Taux de recouvrement brut (avant actualisation/couts) : meilleur si
        # collateral proxy eleve (logement en propriete) ou segment PME/Corporate
        # (garanties professionnelles plus frequentes).
        baseRecovery = 0.35
        collateralEffect = defaultedFrame["housingCollateralProxyScore"].fillna(0) * 0.10
        segmentEffect = np.where(defaultedFrame["perimeterSegment"] == "CORPORATE_SME", 0.12,
                          np.where(defaultedFrame["perimeterSegment"] == "RETAIL_SME", 0.06, 0.0))
        noise = randomState.normal(0, 0.12, size=nDefaulted)
        simulatedRecoveryRate = np.clip(baseRecovery + collateralEffect.values + segmentEffect + noise, 0.02, 0.95)

        simulatedRecoveryMonths = randomState.integers(
            config.RECOVERY_HORIZON_MONTHS_MIN, config.RECOVERY_HORIZON_MONTHS_MAX + 1, size=nDefaulted
        )
        simulatedDirectCost = config.DIRECT_COST_RATE_OF_EAD * (1 + randomState.normal(0, 0.2, size=nDefaulted)).clip(0.3, 2.0)
        simulatedIndirectCost = config.INDIRECT_COST_RATE_OF_EAD * (1 + randomState.normal(0, 0.2, size=nDefaulted)).clip(0.3, 2.0)

        recoveryRate[isDefaulted.values] = simulatedRecoveryRate
        recoveryMonths[isDefaulted.values] = simulatedRecoveryMonths
        directCost[isDefaulted.values] = simulatedDirectCost
        indirectCost[isDefaulted.values] = simulatedIndirectCost

    portfolioFrame["recoveryRateGross"] = recoveryRate
    portfolioFrame["recoveryHorizonMonths"] = recoveryMonths
    portfolioFrame["directCostRate"] = directCost
    portfolioFrame["indirectCostRate"] = indirectCost
    return portfolioFrame


def computeRealizedLgd(portfolioFrame):
    """
    Actualise le recouvrement brut au taux config.RECOVERY_DISCOUNT_RATE_ANNUAL
    sur l'horizon de recouvrement, deduit les couts directs/indirects, et
    calcule la LGD realisee = 1 - recouvrement_net_actualise.
    """
    portfolioFrame = portfolioFrame.copy()
    monthlyDiscountRate = config.RECOVERY_DISCOUNT_RATE_ANNUAL / 12
    discountFactor = 1 / (1 + monthlyDiscountRate) ** portfolioFrame["recoveryHorizonMonths"]

    grossRecoveryPv = portfolioFrame["recoveryRateGross"] * discountFactor
    netRecoveryPv = grossRecoveryPv - portfolioFrame["directCostRate"] - portfolioFrame["indirectCostRate"]

    portfolioFrame["lgdRealized"] = (1 - netRecoveryPv).clip(lower=0.0, upper=1.0)
    return portfolioFrame


def computeSegmentLevelLgd(portfolioFrame):
    """Agrege la LGD realisee au niveau grade x segment (base pour l'application aux encours vivants)."""
    lgdBySegment = (
        portfolioFrame.loc[portfolioFrame["lgdRealized"].notna()]
        .groupby(["riskGradeClass", "perimeterSegment"])["lgdRealized"]
        .mean()
    )
    return lgdBySegment


def computeDownturnLgd(portfolioFrame, lgdBySegment):
    """
    LGD downturn (Art. 181(1)(b) CRR) : pour chaque cellule grade x segment,
    on retient le plus conservateur entre la LGD moyenne "tout cycle" et la
    LGD moyenne observee sur les seuls millesimes de choc.
    """
    downturnMask = portfolioFrame["vintageYear"].isin(config.DOWNTURN_YEARS) & portfolioFrame["lgdRealized"].notna()
    lgdDownturnOnly = portfolioFrame.loc[downturnMask].groupby(["riskGradeClass", "perimeterSegment"])["lgdRealized"].mean()

    combined = pd.concat([lgdBySegment.rename("lgdAllCycle"), lgdDownturnOnly.rename("lgdDownturnOnly")], axis=1)
    combined["lgdDownturnFinal"] = combined[["lgdAllCycle", "lgdDownturnOnly"]].max(axis=1)
    combined["lgdDownturnFinal"] = combined["lgdDownturnFinal"].fillna(combined["lgdAllCycle"])
    return combined["lgdDownturnFinal"]


def attachLgdToLiveBook(portfolioFrame, lgdDownturnFinal, portfolioWideMedianLgd):
    """
    Applique la LGD downturn (grade x segment) a TOUS les dossiers, y compris
    ceux non encore en defaut (necessaire pour calculer l'ECL/RWA des
    encours sains, qui utilisent une LGD estimee et non une LGD realisee).
    """
    portfolioFrame = portfolioFrame.copy()
    lookupKey = list(zip(portfolioFrame["riskGradeClass"], portfolioFrame["perimeterSegment"]))
    portfolioFrame["lgdDownturnEstimate"] = [lgdDownturnFinal.get(key, portfolioWideMedianLgd) for key in lookupKey]
    return portfolioFrame


def runLgdEstimation(portfolioFrame):
    print("*" * 10)
    print("ETAPE 8 - LGD PAR METHODE WORKOUT (COUTS + RECOUVREMENTS SIMULES)")
    print("*" * 10)

    randomState = np.random.default_rng(config.RANDOM_SEED + 2)

    portfolioFrame = simulateRecoveryComponents(portfolioFrame, randomState)
    portfolioFrame = computeRealizedLgd(portfolioFrame)

    lgdBySegment = computeSegmentLevelLgd(portfolioFrame)
    lgdDownturnFinal = computeDownturnLgd(portfolioFrame, lgdBySegment)
    portfolioWideMedianLgd = portfolioFrame["lgdRealized"].median()
    if pd.isna(portfolioWideMedianLgd):
        portfolioWideMedianLgd = 0.45

    portfolioFrame = attachLgdToLiveBook(portfolioFrame, lgdDownturnFinal, portfolioWideMedianLgd)

    print(f"[lgdEstimation] LGD realisee moyenne (defauts simules) : {portfolioFrame['lgdRealized'].mean():.2%}")
    print(f"[lgdEstimation] LGD downturn moyenne appliquee au livre : {portfolioFrame['lgdDownturnEstimate'].mean():.2%}")

    return portfolioFrame
