"""
pdCalibration.py
Etape 7 : calibration de la PD Long Run Average (LRA), EBA GL/2017/16 (par. 88-94).

Utilise le PANEL D'OBSERVATIONS ANNUELLES (performancePanel), construit dans
Tcg.buildAnnualPerformancePanel, et non une fenetre unique a l'octroi :
chaque dossier peut apparaitre a plusieurs annees de performance (t0, t0+12m,
t0+24m, ...), ce qui capture correctement les defauts tardifs (ex. un pret
origine en 2011 qui fait defaut en 2014 est compte a l'observation 2013,
fenetre 2013->2014).

CHANGEMENT METHODOLOGIQUE (suite a l'introduction de populationSegmentation.py,
etape 5) : la LRA n'est plus calibree par SEUL grade de risque, mais par la
PAIRE (populationSegment, riskGradeClass). C'est la traduction operationnelle
directe du principe qui a motive la segmentation de population : deux
obligors classes tous deux "veryLow" mais appartenant a des populations de
capacite economique differente (ex. populationModeste vs populationAisee)
ne recoivent PAS necessairement la meme PD LRA - seule la paire
(population, grade) porte une PD unique. Le grade seul (ex. "veryLow") reste
utilise comme etiquette d'affichage/ordre, mais n'est plus, a lui seul, la
cle de calibration.

CREDIBILITE ACTUARIELLE (nouveaute) : la stratification a trois facteurs
(population x grade x annee) fragmente le panel et peut produire des
cellules a tres faible effectif (quelques observations annuelles). Sur une
cellule aussi fine, un taux de defaut brut de 0% ou 100% est plus souvent le
fruit du hasard d'echantillonnage que la vraie signature de risque du
segment. Avant tout controle de monotonie, chaque cellule est donc ramenee
vers le taux de defaut moyen de sa POPULATION (le "prior"), avec un poids
proportionnel a son propre effectif (facteur de credibilite de Buhlmann,
Z = n / (n + config.LRA_CREDIBILITY_K)) : plus une cellule est documentee,
plus sa propre donnee pese ; plus elle est fine, plus elle est tiree vers le
prior de sa population.
"""

import numpy as np
import pandas as pd
from src import config


def buildAnnualDefaultRateByGrade(portfolioFrame, performancePanel):
    """
    Rattache la paire (populationSegment, riskGradeClass), fixee a l'octroi
    (cf. populationSegmentation.py / riskClustering.py), a chaque observation
    du panel, puis construit la table
    [populationSegment x riskGradeClass x performanceYear] du taux de
    defaut a 12 mois. C'est la matiere premiere de la LRA.
    """
    panelWithGrade = performancePanel.merge(
        portfolioFrame[["obligorId", "populationSegment", "riskGradeClass"]], on="obligorId", how="left"
    )
    annualTable = (
        panelWithGrade.groupby(["populationSegment", "riskGradeClass", "performanceYear"])["default12mFlag"]
        .agg(observationCount="count", annualDefaultRate="mean")
        .reset_index()
    )
    return annualTable


def computeRawLongRunAveragePd(annualTable):
    """
    PD_LRA_brute(population, grade) = moyenne simple des taux de defaut
    annuels de la cellule sur l'ensemble des annees de performance
    disponibles (non ponderee par l'effectif, afin de ne pas ecraser le
    poids des annees de choc qui comptent generalement moins d'observations
    -> conforme a l'esprit "representativite du cycle" de l'EBA GL/2017/16).
    """
    lraByCell = annualTable.groupby(["populationSegment", "riskGradeClass"])["annualDefaultRate"].mean()
    lraByCell.name = "pdLongRunAverageRaw"
    return lraByCell


def computeCredibilityWeightedLra(annualTable):
    """
    Applique la credibilite de Buhlmann : chaque cellule (population, grade)
    est ramenee vers le taux de defaut moyen PONDERE (par le nombre
    d'observations) de sa population, avec un facteur de credibilite
    Z = n_cellule / (n_cellule + config.LRA_CREDIBILITY_K).
    """
    cellStats = (
        annualTable.assign(defaultCountImplied=annualTable["annualDefaultRate"] * annualTable["observationCount"])
        .groupby(["populationSegment", "riskGradeClass"])
        .agg(totalObservations=("observationCount", "sum"), totalDefaults=("defaultCountImplied", "sum"))
        .reset_index()
    )
    cellStats["rawRate"] = cellStats["totalDefaults"] / cellStats["totalObservations"]

    populationStats = (
        cellStats.groupby("populationSegment")
        .agg(populationObservations=("totalObservations", "sum"), populationDefaults=("totalDefaults", "sum"))
        .reset_index()
    )
    populationStats["priorRate"] = populationStats["populationDefaults"] / populationStats["populationObservations"]

    cellStats = cellStats.merge(populationStats[["populationSegment", "priorRate"]], on="populationSegment")
    credibilityFactor = cellStats["totalObservations"] / (cellStats["totalObservations"] + config.LRA_CREDIBILITY_K)
    cellStats["pdLongRunAverageGrade"] = (
        credibilityFactor * cellStats["rawRate"] + (1 - credibilityFactor) * cellStats["priorRate"]
    )
    cellStats["credibilityFactorZ"] = credibilityFactor

    lraByCell = cellStats.set_index(["populationSegment", "riskGradeClass"])["pdLongRunAverageGrade"]
    return lraByCell, cellStats


def enforceMonotonicity(lraByCell):
    """
    Impose la monotonie veryLow < low < medium < high < veryHigh (Art. 170
    CRR) via un Pool Adjacent Violators Algorithm (PAVA) simple, applique
    INDEPENDAMMENT A L'INTERIEUR DE CHAQUE populationSegment (la monotonie
    n'a de sens qu'entre grades d'une meme population ; rien n'impose par
    exemple que veryHigh(populationModeste) soit superieur a
    veryLow(populationAisee), meme si c'est generalement le cas en pratique).
    outlierReview (rattache a populationOutlierReview) n'est jamais lisse.
    """
    correctedRecords = []
    populations = list(lraByCell.index.get_level_values("populationSegment").unique())

    for population in populations:
        cellsForPopulation = lraByCell.xs(population, level="populationSegment")

        if population == "populationOutlierReview":
            for grade, value in cellsForPopulation.items():
                correctedRecords.append((population, grade, value))
            continue

        orderedGrades = [g for g in config.RISK_GRADE_LABELS_ORDERED if g in cellsForPopulation.index]
        values = cellsForPopulation.loc[orderedGrades].values.astype(float).copy()

        changed = True
        while changed:
            changed = False
            for i in range(len(values) - 1):
                if values[i] > values[i + 1]:
                    poolAverage = (values[i] + values[i + 1]) / 2
                    values[i] = poolAverage
                    values[i + 1] = poolAverage
                    changed = True

        for grade, value in zip(orderedGrades, values):
            correctedRecords.append((population, grade, value))

    monotonicSeries = pd.Series(
        {(p, g): v for p, g, v in correctedRecords}, name="pdLongRunAverageGrade"
    )
    monotonicSeries.index = pd.MultiIndex.from_tuples(monotonicSeries.index, names=["populationSegment", "riskGradeClass"])
    return monotonicSeries


def attachPdLraToPortfolio(portfolioFrame, lraByCell):
    portfolioFrame = portfolioFrame.copy()
    lookupKey = list(zip(portfolioFrame["populationSegment"], portfolioFrame["riskGradeClass"]))
    portfolioFrame["pdLongRunAverageGrade"] = [lraByCell.get(key, np.nan) for key in lookupKey]
    return portfolioFrame


def runPdCalibration(portfolioFrame, performancePanel):
    print("*" * 10)
    print("ETAPE 7 - CALIBRATION DE LA PD LONG RUN AVERAGE (LRA) PAR (POPULATION x GRADE) - EBA GL/2017/16")
    print("*" * 10)

    annualTable = buildAnnualDefaultRateByGrade(portfolioFrame, performancePanel)

    rawLraByCell = computeRawLongRunAveragePd(annualTable)
    credibilityLraByCell, credibilityDetail = computeCredibilityWeightedLra(annualTable)

    print("[pdCalibration] Effet de la credibilite de Buhlmann (LRA brute -> LRA credibilisee), par cellule :")
    displayDetail = credibilityDetail.copy()
    displayDetail["pdLongRunAverageBrute"] = displayDetail["rawRate"]
    print(
        displayDetail.set_index(["populationSegment", "riskGradeClass"])[
            ["totalObservations", "credibilityFactorZ", "pdLongRunAverageBrute", "pdLongRunAverageGrade"]
        ].applymap(lambda x: f"{x:.4f}" if isinstance(x, float) else x).to_string()
    )

    lraByCell = enforceMonotonicity(credibilityLraByCell)

    portfolioFrame = attachPdLraToPortfolio(portfolioFrame, lraByCell)

    nYearsByCell = annualTable.groupby(["populationSegment", "riskGradeClass"])["performanceYear"].nunique()
    print(f"\n[pdCalibration] Nombre d'annees de performance utilisees par cellule (population x grade) :")
    print(nYearsByCell.to_string())
    print("[pdCalibration] PD Long Run Average par (population x grade), apres credibilite + controle de monotonie intra-population :")
    print(lraByCell.apply(lambda x: f"{x:.4%}").to_string())

    return portfolioFrame, annualTable, lraByCell
