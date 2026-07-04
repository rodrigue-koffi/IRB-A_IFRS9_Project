"""
pdCalibration.py
Etape 6 : calibration de la PD Long Run Average (LRA), EBA GL/2017/16 (§88-94).

Utilise desormais le PANEL D'OBSERVATIONS ANNUELLES (performancePanel), construit
dans Tcg.buildAnnualPerformancePanel, et non plus une
fenetre unique a l'octroi : chaque dossier peut apparaitre a plusieurs annees
de performance (t0, t0+12m, t0+24m, ...), ce qui capture correctement les
defauts tardifs (ex. un pret origine en 2011 qui fait defaut en 2014 est
compte a l'observation 2013, fenetre 2013->2014).
"""

import numpy as np
import pandas as pd
from src import config


def buildAnnualDefaultRateByGrade(portfolioFrame, performancePanel):
    """
    Rattache le grade de risque (fixe a l'octroi, cf. riskClustering.py) a
    chaque observation du panel, puis construit la table
    [riskGradeClass x performanceYear] du taux de defaut a 12 mois.
    C'est la matiere premiere de la LRA.
    """
    panelWithGrade = performancePanel.merge(
        portfolioFrame[["obligorId", "riskGradeClass"]], on="obligorId", how="left"
    )
    annualTable = (
        panelWithGrade.groupby(["riskGradeClass", "performanceYear"])["default12mFlag"]
        .agg(observationCount="count", annualDefaultRate="mean")
        .reset_index()
    )
    return annualTable


def computeLongRunAveragePd(annualTable):
    """
    PD_LRA(grade) = moyenne simple des taux de defaut annuels du grade sur
    l'ensemble des annees de performance disponibles (non ponderee par
    l'effectif, afin de ne pas ecraser le poids des annees de choc qui
    comptent generalement moins d'observations -> conforme a l'esprit
    "representativite du cycle" de l'EBA GL/2017/16).
    """
    lraByGrade = annualTable.groupby("riskGradeClass")["annualDefaultRate"].mean()
    lraByGrade.name = "pdLongRunAverageGrade"
    return lraByGrade


def enforceMonotonicity(lraByGrade):
    """Impose la monotonie veryLow < low < medium < high < veryHigh (Art. 170 CRR)
    via un Pool Adjacent Violators Algorithm (PAVA) simple."""
    orderedGrades = [g for g in config.RISK_GRADE_LABELS_ORDERED if g in lraByGrade.index]
    values = lraByGrade.loc[orderedGrades].values.astype(float).copy()

    changed = True
    while changed:
        changed = False
        for i in range(len(values) - 1):
            if values[i] > values[i + 1]:
                poolAverage = (values[i] + values[i + 1]) / 2
                values[i] = poolAverage
                values[i + 1] = poolAverage
                changed = True

    monotonicSeries = pd.Series(values, index=orderedGrades, name="pdLongRunAverageGrade")
    if "outlierReview" in lraByGrade.index:
        monotonicSeries.loc["outlierReview"] = lraByGrade.loc["outlierReview"]
    return monotonicSeries


def attachPdLraToPortfolio(portfolioFrame, lraByGrade):
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["pdLongRunAverageGrade"] = portfolioFrame["riskGradeClass"].map(lraByGrade)
    return portfolioFrame


def runPdCalibration(portfolioFrame, performancePanel):
    print("*" * 10)
    print("ETAPE 6 - CALIBRATION DE LA PD LONG RUN AVERAGE (LRA) - EBA GL/2017/16")
    print("*" * 10)

    annualTable = buildAnnualDefaultRateByGrade(portfolioFrame, performancePanel)
    lraByGrade = computeLongRunAveragePd(annualTable)
    lraByGrade = enforceMonotonicity(lraByGrade)

    portfolioFrame = attachPdLraToPortfolio(portfolioFrame, lraByGrade)

    nYearsByGrade = annualTable.groupby("riskGradeClass")["performanceYear"].nunique()
    print(f"[pdCalibration] Nombre d'annees de performance utilisees par grade : "
          f"{nYearsByGrade.to_dict()}")
    print("[pdCalibration] PD Long Run Average par grade (apres controle de monotonie) :")
    print(lraByGrade.apply(lambda x: f"{x:.4%}").to_string())

    return portfolioFrame, annualTable, lraByGrade
