"""
modelValidation.py
===================

Validation statistique du systeme de notation : pouvoir discriminant (AUC / Gini),
stabilite temporelle (decoupage Train / Out-Of-Time) et colinearite des variables
de segmentation (VIF).

Contexte
--------
Le classement de risque (riskGradeClass, cf. riskClustering.py) est desormais
construit EN DEUX TEMPS : une segmentation de POPULATION non supervisee
(DBSCAN + KMeans, populationSegmentation.py, etape 5) puis, a l'interieur de
chaque population, une segmentation de RISQUE supervisee par le defaut
(algorithme de Belson, riskClustering.py, etape 6). Une consequence directe :
le meme LIBELLE de grade (ex. "veryLow") ne porte pas necessairement le meme
niveau de PD selon la population a laquelle il appartient (cf.
pdCalibration.py). Le rang utilise pour l'AUC/Gini ne peut donc plus etre le
simple rang du libelle (0=veryLow ... 4=veryHigh) : il doit refleter le
niveau REEL de PD finale calibree (pdFinalRegulatory) de la cellule
(population, grade) a laquelle appartient chaque obligor. C'est ce rang,
et non plus le rang du seul libelle, qui est utilise ci-dessous comme score
pour l'AUC/Gini.

EBA/GL/2017/16 (Titre III, section sur la validation) demande explicitement
de verifier que l'ordre des classes de risque ("rank ordering") separe
correctement les bons et mauvais payeurs, quelle que soit la methode
d'affectation des classes. Le decoupage Train/OOT ci-dessous mesure la
stabilite de ce rang dans le temps.

Limite assumee et documentee : la construction des classes (riskClustering.py)
utilise deja `defaultEverFlag`, calcule sur l'historique complet
(train + out-of-time) - c'est une consequence du caractere SUPERVISE de
l'algorithme de Belson (cf. docstring de riskClustering.py), plus marquee que
dans l'ancienne version (KMeans non supervise). Le decoupage Train/OOT
ci-dessous mesure donc la stabilite du pouvoir discriminant du grade dans le
temps, pas une validation "hors echantillon" au sens strict d'un modele
reestime uniquement sur le train. Un futur raffinement consisterait a
reconstruire l'arbre de Belson en n'utilisant que les defauts anterieurs a
OOT_START_YEAR.

Aucun module logging : tracabilite par impressions structurees (print),
conforme a la convention du projet.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LinearRegression

from src import config
from src.riskClustering import CLUSTERING_FEATURES
from src.populationSegmentation import POPULATION_SEGMENTATION_FEATURES


def buildPdRankSeries(portfolioFrame):
    """
    Rang dense de la PD finale reglementaire moyenne de chaque cellule
    (populationSegment, riskGradeClass), croissant avec le risque. Remplace
    le rang du seul libelle de grade (insuffisant depuis que le meme
    libelle peut porter des PD differentes selon la population).
    """
    cellMeanPd = (
        portfolioFrame.groupby(["populationSegment", "riskGradeClass"])["pdFinalRegulatory"]
        .mean()
        .rank(method="dense")
    )
    lookupKey = list(zip(portfolioFrame["populationSegment"], portfolioFrame["riskGradeClass"]))
    return pd.Series([cellMeanPd.get(key, np.nan) for key in lookupKey], index=portfolioFrame.index)


def splitTrainOot(performancePanel, ootStartYear=config.OOT_START_YEAR):
    trainPanel = performancePanel[performancePanel["performanceYear"] < ootStartYear].copy()
    ootPanel = performancePanel[performancePanel["performanceYear"] >= ootStartYear].copy()
    return trainPanel, ootPanel


def computeDiscriminatoryPower(panelSubset, portfolioFrame, label):
    if panelSubset.empty:
        return {"echantillon": label, "observations": 0, "tauxDefaut": np.nan, "auc": np.nan, "gini": np.nan}

    merged = panelSubset.merge(
        portfolioFrame[["obligorId", "populationSegment", "riskGradeClass", "pdRank"]], on="obligorId", how="left"
    )
    merged = merged.dropna(subset=["pdRank", "default12mFlag"])

    defaultRate = merged["default12mFlag"].mean()
    nUniqueOutcomes = merged["default12mFlag"].nunique()

    if nUniqueOutcomes < 2 or merged.empty:
        auc = np.nan
        gini = np.nan
    else:
        auc = roc_auc_score(merged["default12mFlag"], merged["pdRank"])
        gini = 2 * auc - 1

    return {
        "echantillon": label,
        "observations": len(merged),
        "tauxDefaut": defaultRate,
        "auc": auc,
        "gini": gini,
    }


def computeVif(portfolioFrame, featureColumns, moduleLabel):
    workingFrame = portfolioFrame[featureColumns].copy()
    workingFrame = workingFrame.apply(pd.to_numeric, errors="coerce")
    workingFrame = workingFrame.fillna(workingFrame.median(numeric_only=True))

    vifRecords = []
    for targetColumn in featureColumns:
        predictorColumns = [c for c in featureColumns if c != targetColumn]
        regression = LinearRegression()
        regression.fit(workingFrame[predictorColumns], workingFrame[targetColumn])
        rSquared = regression.score(workingFrame[predictorColumns], workingFrame[targetColumn])
        rSquared = min(rSquared, 0.999999)
        vif = 1.0 / (1.0 - rSquared)
        vifRecords.append({"module": moduleLabel, "variable": targetColumn, "rSquared": rSquared, "vif": vif})

    vifTable = pd.DataFrame(vifRecords).sort_values("vif", ascending=False).reset_index(drop=True)
    return vifTable


def runModelValidation(portfolioFrame, performancePanel):
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["pdRank"] = buildPdRankSeries(portfolioFrame)

    trainPanel, ootPanel = splitTrainOot(performancePanel)

    discriminationResults = pd.DataFrame([
        computeDiscriminatoryPower(performancePanel, portfolioFrame, "Ensemble du panel"),
        computeDiscriminatoryPower(trainPanel, portfolioFrame, f"Train (< {config.OOT_START_YEAR})"),
        computeDiscriminatoryPower(ootPanel, portfolioFrame, f"Out-Of-Time (>= {config.OOT_START_YEAR})"),
    ])

    vifTable = pd.concat([
        computeVif(portfolioFrame, POPULATION_SEGMENTATION_FEATURES, "populationSegmentation (etape 5)"),
        computeVif(portfolioFrame, CLUSTERING_FEATURES, "riskClustering / Belson (etape 6)"),
    ], ignore_index=True)

    print("\n[VALIDATION] Pouvoir discriminant (AUC / Gini, score = rang de la PD finale par cellule) par echantillon :")
    for _, row in discriminationResults.iterrows():
        if pd.isna(row["auc"]):
            print(f"  - {row['echantillon']:<28} obs={row['observations']:<6} AUC=n/a (classe unique)")
        else:
            print(
                f"  - {row['echantillon']:<28} obs={row['observations']:<6} "
                f"tauxDefaut={row['tauxDefaut']:.4f}  AUC={row['auc']:.4f}  Gini={row['gini']:.4f}"
            )

    print("\n[VALIDATION] VIF des variables de segmentation (seuil d'alerte usuel : 5) :")
    for _, row in vifTable.iterrows():
        flag = "  <-- a surveiller" if row["vif"] > 5 else ""
        print(f"  - [{row['module']}] {row['variable']:<32} VIF={row['vif']:.2f}{flag}")

    return discriminationResults, vifTable


if __name__ == "__main__":
    from src.dataIngestion import runDataIngestion
    from src.perimeterDefinition import runPerimeterDefinition
    from src.Tcg import runTemporalChronologyGeneration
    from src.featureEngineering import runFeatureEngineering
    from src.populationSegmentation import runPopulationSegmentation
    from src.riskClustering import runRiskClustering
    from src.pdCalibration import runPdCalibration
    from src.marginOfConservatism import runMarginOfConservatism
    from src.lgdEstimation import runLgdEstimation
    from src.eadEstimation import runEadEstimation
    from src.ifrs9Staging import runIfrs9Staging
    from src.irbCapitalRwa import runIrbCapitalRwa

    portfolioFrame = runDataIngestion()
    portfolioFrame = runPerimeterDefinition(portfolioFrame)
    portfolioFrame, performancePanel = runTemporalChronologyGeneration(portfolioFrame)
    portfolioFrame = runFeatureEngineering(portfolioFrame)
    portfolioFrame = runPopulationSegmentation(portfolioFrame)
    portfolioFrame, anovaTable, belsonTreeSummary = runRiskClustering(portfolioFrame)
    portfolioFrame, annualTable, lraByCell = runPdCalibration(portfolioFrame, performancePanel)
    portfolioFrame = runMarginOfConservatism(portfolioFrame, annualTable, lraByCell)
    portfolioFrame = runLgdEstimation(portfolioFrame)
    portfolioFrame = runEadEstimation(portfolioFrame)
    portfolioFrame = runIfrs9Staging(portfolioFrame)
    portfolioFrame = runIrbCapitalRwa(portfolioFrame)

    discriminationResults, vifTable = runModelValidation(portfolioFrame, performancePanel)

    print("\n[VERIFICATION] modelValidation.py OK")
    print(discriminationResults.to_string(index=False))
    print(vifTable.to_string(index=False))
