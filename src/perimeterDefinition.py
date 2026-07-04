"""
perimeterDefinition.py
=======================
Etape 2 / : definition du perimetre reglementaire (scope of
application) AVANT toute modelisation. C'est une etape de gouvernance a part
entiere : un modele IRB est toujours documente pour un perimetre precis
(CRR Art. 142 - classes d'exposition ; Art. 147 - definition des classes ;
Art. 123 - critere retail : exposition a une personne physique ou une PME,
granularite, exposition totale groupe < 1 M EUR).

Le jeu de donnees source est un portefeuille de credit a la consommation
(Retail pur). Pour demontrer la capacite a "cercler" un perimetre
heterogene (exercice frequent en gouvernance des modeles : un portefeuille
Retail contient toujours une frange de dossiers a requalifier), on simule
une sous-population PME a partir des dossiers dont l'objet du pret est
'business' et dont le profil (competence professionnelle elevee, montant
plus consequent) est coherent avec une activite independante.

AVERTISSEMENT METHODOLOGIQUE (documente egalement dans docs/METHODOLOGY.md) :
Les montants du jeu de donnees restent tous tres inferieurs au seuil de
1 M EUR de l'art. 123 CRR. En toute rigueur, ces expositions resteraient
donc dans le portefeuille Retail meme si l'obligor est une PME (retail SME).
Le segment "CORPORATE_SME" cree ici est un choix pedagogique assume : il
permet d'illustrer l'ajustement de correlation "taille de firme" (Art. 153(4))
et le facteur supportant PME (Art. 501) dans irbCapitalRwa.py.
"""

import numpy as np
import pandas as pd
from src import config


def flagSmeCandidates(portfolioFrame):
    """Identifie les dossiers eligibles a un profil PME (proxy metier)."""
    portfolioFrame = portfolioFrame.copy()
    isBusinessPurpose = portfolioFrame["purpose"].astype(str).str.lower().eq("business")
    isSkilledJob = portfolioFrame["jobSkillLevel"] >= 2
    isMaterialAmount = portfolioFrame["creditAmount"] >= portfolioFrame["creditAmount"].median()
    portfolioFrame["smeEligibleProxy"] = isBusinessPurpose & isSkilledJob & isMaterialAmount
    return portfolioFrame


def assignPerimeterSegment(portfolioFrame, randomState):
    """
    Affecte chaque obligor a un segment de perimetre :
      - RETAIL_CONSUMER : particulier, credit a la consommation classique
      - RETAIL_SME      : petite activite independante, reste sous le seuil
                           art. 123 -> traite en Retail (cas le plus realiste ici)
      - CORPORATE_SME    : sous-ensemble minoritaire simule pour la demonstration
                           de l'ajustement de correlation taille de firme
    """
    portfolioFrame = flagSmeCandidates(portfolioFrame)
    portfolioFrame = portfolioFrame.copy()

    eligibleIndex = portfolioFrame.index[portfolioFrame["smeEligibleProxy"]]
    targetSmeCount = int(round(config.SME_TARGET_SHARE * len(portfolioFrame)))
    targetSmeCount = min(targetSmeCount, len(eligibleIndex))

    chosenSmeIndex = randomState.choice(eligibleIndex, size=targetSmeCount, replace=False) if targetSmeCount > 0 else []

    portfolioFrame["perimeterSegment"] = "RETAIL_CONSUMER"
    portfolioFrame.loc[chosenSmeIndex, "perimeterSegment"] = "RETAIL_SME"

    # Parmi les PME simulees, un tiers est bascule en "CORPORATE_SME" pour
    # illustrer explicitement le franchissement conceptuel de perimetre.
    corporateCandidates = randomState.choice(
        chosenSmeIndex, size=int(len(chosenSmeIndex) / 3), replace=False
    ) if len(chosenSmeIndex) > 0 else []
    portfolioFrame.loc[corporateCandidates, "perimeterSegment"] = "CORPORATE_SME"

    return portfolioFrame


def simulateRetailIncomeData(portfolioFrame, randomState):
    """
    Genere un revenu mensuel simule (donnee absente de la base source mais
    indispensable pour tout ratio d'endettement Retail). Le revenu est
    correlee au niveau de qualification professionnelle et a l'age, avec un
    bruit individuel, pour rester plausible.
    """
    portfolioFrame = portfolioFrame.copy()
    baseIncomeByJobLevel = {0: 900, 1: 1400, 2: 2200, 3: 3400}
    baseIncome = portfolioFrame["jobSkillLevel"].map(baseIncomeByJobLevel).fillna(1400)
    ageAdjustment = (portfolioFrame["age"].clip(upper=55) - 25).clip(lower=0) * 12
    noise = randomState.normal(loc=1.0, scale=0.18, size=len(portfolioFrame)).clip(0.6, 1.6)
    portfolioFrame["monthlyIncomeEur"] = ((baseIncome + ageAdjustment) * noise).round(0)
    return portfolioFrame


def simulateSmeFinancials(portfolioFrame, randomState):
    """Genere chiffre d'affaires et effectif pour les dossiers PME/Corporate."""
    portfolioFrame = portfolioFrame.copy()
    isSmeLike = portfolioFrame["perimeterSegment"].isin(["RETAIL_SME", "CORPORATE_SME"])
    nSme = int(isSmeLike.sum())

    turnover = np.full(len(portfolioFrame), np.nan)
    employees = np.full(len(portfolioFrame), np.nan)

    if nSme > 0:
        simulatedTurnover = randomState.uniform(
            config.SME_TURNOVER_MIN_EUR, config.SME_TURNOVER_MAX_EUR, size=nSme
        )
        simulatedEmployees = randomState.integers(2, 49, size=nSme)
        turnover[isSmeLike.values] = simulatedTurnover
        employees[isSmeLike.values] = simulatedEmployees

    portfolioFrame["smeAnnualTurnoverEur"] = turnover
    portfolioFrame["smeEmployeeCount"] = employees
    return portfolioFrame


def runPerimeterDefinition(portfolioFrame):
    print("$" * 10)
    print("ETAPE 2 - DEFINITION DU PERIMETRE (RETAIL / PME / CORPORATE-SME)")
    print("$" * 10)

    randomState = np.random.default_rng(config.RANDOM_SEED)

    portfolioFrame = assignPerimeterSegment(portfolioFrame, randomState)
    portfolioFrame = simulateRetailIncomeData(portfolioFrame, randomState)
    portfolioFrame = simulateSmeFinancials(portfolioFrame, randomState)

    segmentCounts = portfolioFrame["perimeterSegment"].value_counts()
    for segmentName, count in segmentCounts.items():
        print(f"[perimeterDefinition] {segmentName} : {count} obligors ({count/len(portfolioFrame):.1%})")

    return portfolioFrame
