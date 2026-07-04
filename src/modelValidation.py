"""
modelValidation.py
===================

Validation statistique du systeme de notation : pouvoir discriminant (AUC / Gini),
stabilite temporelle (decoupage Train / Out-Of-Time) et colinearite des variables
de segmentation (VIF).

Contexte
--------
Le classement de risque (riskGradeClass, cf. riskClustering.py) est produit par
un clustering non supervise (DBSCAN + KMeans), pas par une regression logistique
notant chaque dossier avec un score continu. Cela ne dispense pas de valider son
pouvoir discriminant : EBA/GL/2017/16 (Titre III, section sur la validation)
demande explicitement de verifier que l'ordre des classes de risque ("rank
ordering") separe correctement les bons et mauvais payeurs, quelle que soit la
methode d'affectation des classes.

Le "score" utilise pour l'AUC/Gini est donc le rang ordinal du grade
(veryLow=0 ... veryHigh=4, outlierReview=5, traite comme le rang le plus risque
car il correspond a une population ecartee du clustering principal faute
d'appartenance claire a un groupe).

Limite assumee et documentee : le classement des clusters par taux de defaut
(cf. riskClustering.py) utilise deja `defaultEverFlag`, calcule sur l'historique
complet (train + out-of-time). Le decoupage Train/OOT ci-dessous mesure donc la
stabilite du pouvoir discriminant du grade dans le temps, pas une validation
"hors echantillon" au sens strict d'un modele reestime uniquement sur le train.
Un futur raffinement consisterait a reordonner les grades en utilisant
uniquement les defauts anterieurs a OOT_START_YEAR.

Aucun module logging : traçabilite par impressions structurees (print), conforme
a la convention du projet.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LinearRegression

from src import config
from src.riskClustering import CLUSTERING_FEATURES

GRADE_RANK_MAP = {
    label: rank for rank, label in enumerate(config.RISK_GRADE_LABELS_ORDERED)
}
GRADE_RANK_MAP["outlierReview"] = len(config.RISK_GRADE_LABELS_ORDERED)


def buildGradeRankSeries(portfolioFrame):
    gradeRank = portfolioFrame["riskGradeClass"].map(GRADE_RANK_MAP)
    return gradeRank


def splitTrainOot(performancePanel, ootStartYear=config.OOT_START_YEAR):
    trainPanel = performancePanel[performancePanel["performanceYear"] < ootStartYear].copy()
    ootPanel = performancePanel[performancePanel["performanceYear"] >= ootStartYear].copy()
    return trainPanel, ootPanel


def computeDiscriminatoryPower(panelSubset, portfolioFrame, label):
    if panelSubset.empty:
        return {"echantillon": label, "observations": 0, "tauxDefaut": np.nan, "auc": np.nan, "gini": np.nan}

    merged = panelSubset.merge(
        portfolioFrame[["obligorId", "riskGradeClass"]], on="obligorId", how="left"
    )
    merged["gradeRank"] = merged["riskGradeClass"].map(GRADE_RANK_MAP)
    merged = merged.dropna(subset=["gradeRank", "default12mFlag"])

    defaultRate = merged["default12mFlag"].mean()
    nUniqueOutcomes = merged["default12mFlag"].nunique()

    if nUniqueOutcomes < 2 or merged.empty:
        auc = np.nan
        gini = np.nan
    else:
        auc = roc_auc_score(merged["default12mFlag"], merged["gradeRank"])
        gini = 2 * auc - 1

    return {
        "echantillon": label,
        "observations": len(merged),
        "tauxDefaut": defaultRate,
        "auc": auc,
        "gini": gini,
    }


def computeVif(portfolioFrame, featureColumns=CLUSTERING_FEATURES):
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
        vifRecords.append({"variable": targetColumn, "rSquared": rSquared, "vif": vif})

    vifTable = pd.DataFrame(vifRecords).sort_values("vif", ascending=False).reset_index(drop=True)
    return vifTable


def runModelValidation(portfolioFrame, performancePanel):
    trainPanel, ootPanel = splitTrainOot(performancePanel)

    discriminationResults = pd.DataFrame([
        computeDiscriminatoryPower(performancePanel, portfolioFrame, "Ensemble du panel"),
        computeDiscriminatoryPower(trainPanel, portfolioFrame, f"Train (< {config.OOT_START_YEAR})"),
        computeDiscriminatoryPower(ootPanel, portfolioFrame, f"Out-Of-Time (>= {config.OOT_START_YEAR})"),
    ])

    vifTable = computeVif(portfolioFrame)

    print("\n[VALIDATION] Pouvoir discriminant (AUC / Gini) par echantillon :")
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
        print(f"  - {row['variable']:<32} VIF={row['vif']:.2f}{flag}")

    return discriminationResults, vifTable


if __name__ == "__main__":
    from src.dataIngestion import runDataIngestion
    from src.perimeterDefinition import runPerimeterDefinition
    from src.Tcg import runTemporalChronologyGeneration
    from src.featureEngineering import runFeatureEngineering
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
    portfolioFrame = runRiskClustering(portfolioFrame)
    portfolioFrame, annualTable, lraByGrade = runPdCalibration(portfolioFrame, performancePanel)
    portfolioFrame = runMarginOfConservatism(portfolioFrame, annualTable, lraByGrade)
    portfolioFrame = runLgdEstimation(portfolioFrame)
    portfolioFrame = runEadEstimation(portfolioFrame)
    portfolioFrame = runIfrs9Staging(portfolioFrame)
    portfolioFrame = runIrbCapitalRwa(portfolioFrame)

    discriminationResults, vifTable = runModelValidation(portfolioFrame, performancePanel)

    print("\n[VERIFICATION] modelValidation.py OK")
    print(discriminationResults.to_string(index=False))
    print(vifTable.to_string(index=False))
