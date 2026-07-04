"""
dataIngestion.py
=================
Etape 1 : chargement et normalisation de la base brute.

Objectif : isoler completement la lecture/nettoyage technique du reste de la
logique metier (separation des responsabilites -> maintenabilite, exigence
implicite de la gouvernance des modeles, CRR Art. 174).
"""

import pandas as pd
from src import config


def loadRawPortfolio():
    """Charge le fichier Excel brut et renomme les colonnes en camelCase explicite."""
    filePath = config.DATA_RAW_DIR / config.RAW_FILE_NAME
    rawFrame = pd.read_excel(filePath, sheet_name=config.RAW_SHEET_NAME)

    columnRenameMap = {
        "Age": "age",
        "Sex": "sex",
        "Job": "jobSkillLevel",
        "Housing": "housingType",
        "Saving accounts": "savingAccountLevel",
        "Checking account": "checkingAccountLevel",
        "Credit amount": "creditAmount",
        "Duration": "durationMonths",
        "Purpose": "purpose",
        "Risk": "creditRiskLabel",
    }
    rawFrame = rawFrame.rename(columns=columnRenameMap)

    print(f"[dataIngestion] Fichier charge : {rawFrame.shape[0]} obligors, {rawFrame.shape[1]} colonnes brutes")
    return rawFrame


def assignObligorIdentifiers(portfolioFrame):
    """Attribue un identifiant obligor stable (equivalent d'une cle client SI Risques)."""
    portfolioFrame = portfolioFrame.reset_index(drop=True).copy()
    portfolioFrame["obligorId"] = ["OBLG-" + str(i + 1).zfill(6) for i in portfolioFrame.index]
    firstColumns = ["obligorId"] + [c for c in portfolioFrame.columns if c != "obligorId"]
    return portfolioFrame[firstColumns]


def handleCategoricalMissingValues(portfolioFrame):
    """
    Les NaN de savingAccountLevel/checkingAccountLevel ne sont PAS des valeurs
    manquantes au hasard : elles signifient "pas de compte de ce type" dans le
    jeu de donnees source. Les coder en categorie explicite 'none' evite un
    biais de traitement (imputation silencieuse = deficience identifiee,
    cf. MoC categorie B dans marginOfConservatism.py).
    """
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["savingAccountLevel"] = portfolioFrame["savingAccountLevel"].fillna("none")
    portfolioFrame["checkingAccountLevel"] = portfolioFrame["checkingAccountLevel"].fillna("none")
    return portfolioFrame


def buildDefaultEverFlag(portfolioFrame):
    """
    Construit le flag 'a fait defaut un jour' a partir du label brut good/bad.
    ATTENTION : ce flag est atemporel (pas de date associee dans la base
    source). Il sert uniquement de verite terrain pour generer une date de
    defaut plausible dans Tcg.py. Le veritable flag
    reglementaire utilise en aval est default12mFlag (fenetre glissante t / t+12m).
    """
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["defaultEverFlag"] = (portfolioFrame["creditRiskLabel"] == "bad").astype(int)
    return portfolioFrame


def runDataIngestion():
    """Point d'entree du module, appele par le pipeline."""
    print("$" * 20)
    print("ETAPE 1 - INGESTION ET NORMALISATION DE LA BASE BRUTE")
    print("$" * 20)

    portfolioFrame = loadRawPortfolio()
    portfolioFrame = assignObligorIdentifiers(portfolioFrame)
    portfolioFrame = handleCategoricalMissingValues(portfolioFrame)
    portfolioFrame = buildDefaultEverFlag(portfolioFrame)

    print(f"[dataIngestion] Taux de defaut brut (ever) : {portfolioFrame['defaultEverFlag'].mean():.2%}")
    return portfolioFrame
