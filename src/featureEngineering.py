"""
featureEngineering.py
======================
Etape 4 : construction des variables de risque a partir des
seules informations disponibles A LA DATE D'OCTROI (originationDate). C'est
un point de vigilance explicite : integrer une variable connue seulement
apres l'octroi (daysPastDue courant) dans un score d'octroi serait une
fuite d'information (look-ahead bias), erreur classique en modelisation du
risque de credit.
"""

import numpy as np
import pandas as pd


ORDINAL_SAVING_MAP = {"none": 0, "little": 1, "moderate": 2, "quite rich": 3, "rich": 4}
ORDINAL_CHECKING_MAP = {"none": 0, "little": 1, "moderate": 2, "rich": 3}
HOUSING_COLLATERAL_PROXY_MAP = {"own": 2, "free": 1, "rent": 0}


def encodeOrdinalRiskDrivers(portfolioFrame):
    """Transforme les variables qualitatives ordonnees en scores numeriques explicites."""
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["savingAccountScore"] = portfolioFrame["savingAccountLevel"].map(ORDINAL_SAVING_MAP)
    portfolioFrame["checkingAccountScore"] = portfolioFrame["checkingAccountLevel"].map(ORDINAL_CHECKING_MAP)
    portfolioFrame["housingCollateralProxyScore"] = portfolioFrame["housingType"].map(HOUSING_COLLATERAL_PROXY_MAP)
    return portfolioFrame


def buildAgeBands(portfolioFrame):
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["ageBand"] = pd.cut(
        portfolioFrame["age"], bins=[0, 25, 35, 50, 100], labels=["young", "adult", "middle", "senior"]
    )
    return portfolioFrame


def buildAffordabilityRatios(portfolioFrame):
    """
    Ratios d'endettement/soutenabilite, calculables uniquement grace au
    revenu simule dans perimeterDefinition.py (absent de la base source).
    """
    portfolioFrame = portfolioFrame.copy()
    annualIncome = (portfolioFrame["monthlyIncomeEur"] * 12).clip(lower=1)

    portfolioFrame["creditToAnnualIncomeRatio"] = portfolioFrame["creditAmount"] / annualIncome

    monthlyInstallmentProxy = portfolioFrame["creditAmount"] / portfolioFrame["durationMonths"].clip(lower=1)
    portfolioFrame["installmentToIncomeRatio"] = monthlyInstallmentProxy / portfolioFrame["monthlyIncomeEur"].clip(lower=1)

    # Transformation monotone (et non "logging applicatif" - cf. config/README) de
    # variables monetaires tres asymetriques, utile a la stabilite des distances
    # euclidiennes dans le clustering (riskClustering.py).
    portfolioFrame["creditAmountScaledLog"] = np.log1p(portfolioFrame["creditAmount"])
    return portfolioFrame


def buildSmeSpecificRatios(portfolioFrame):
    """Ratios specifiques au segment PME/Corporate (chiffre d'affaires, effectifs)."""
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["creditToTurnoverRatio"] = np.where(
        portfolioFrame["smeAnnualTurnoverEur"].notna(),
        portfolioFrame["creditAmount"] / portfolioFrame["smeAnnualTurnoverEur"],
        np.nan,
    )
    return portfolioFrame


def runFeatureEngineering(portfolioFrame):
    print("*" * 10)
    print("ETAPE 4 - FEATURE ENGINEERING (VARIABLES CONNUES A L'OCTROI UNIQUEMENT)")
    print("*" * 10)

    portfolioFrame = encodeOrdinalRiskDrivers(portfolioFrame)
    portfolioFrame = buildAgeBands(portfolioFrame)
    portfolioFrame = buildAffordabilityRatios(portfolioFrame)
    portfolioFrame = buildSmeSpecificRatios(portfolioFrame)

    print(f"[featureEngineering] {portfolioFrame.shape[1]} colonnes apres enrichissement")
    return portfolioFrame
