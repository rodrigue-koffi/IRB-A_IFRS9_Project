"""
riskClustering.py
==================
Etape 5 : constitution des classes de risque par
apprentissage non supervise, PLUTOT QUE par un decoupage arbitraire en
quantiles de la PD (pd.qcut) comme dans la V3 . Un decoupage en
quantiles impose artificiellement 20% d'effectif par classe : ce n'est pas
une segmentation par homogeneite de risque, c'est une segmentation par
taille d'echantillon. L'art. 170 CRR exige au contraire une differenciation
du risque fondee sur des caracteristiques homogenes intra-classe et
heterogenes inter-classes.

Methode retenue :
  1. DBSCAN sur les variables standardisees -> detection des dossiers
     atypiques (bruit, label -1). Ces dossiers sont isoles dans un segment
     "outlierReviewSegment" et exclus du KMeans (ils justifient une revue
     manuelle / un override, pratique standard en gouvernance des notations).
  2. KMeans (k=5) sur la population "coeur" (hors bruit DBSCAN) ->
     regroupement en 5 pools de risque homogenes.
  3. Les clusters bruts de KMeans n'ont pas d'ordre intrinseque (le cluster
     0 n'est pas forcement le moins risque) : ils sont donc classes par taux
     de defaut observe (defaultEverFlag, seule verite terrain disponible au
     niveau obligor) croissant, puis
     mappes vers les etiquettes ordonnees veryLow -> veryHigh.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

from src import config

CLUSTERING_FEATURES = [
    "age",
    "jobSkillLevel",
    "savingAccountScore",
    "checkingAccountScore",
    "housingCollateralProxyScore",
    "creditAmountScaledLog",
    "durationMonths",
    "installmentToIncomeRatio",
    "creditToAnnualIncomeRatio",
]


def prepareClusteringMatrix(portfolioFrame):
    """Selectionne et standardise les variables de risque utilisees pour le clustering."""
    featureFrame = portfolioFrame[CLUSTERING_FEATURES].copy()
    featureFrame = featureFrame.replace([np.inf, -np.inf], np.nan)
    featureFrame = featureFrame.fillna(featureFrame.median(numeric_only=True))

    scaler = StandardScaler()
    scaledMatrix = scaler.fit_transform(featureFrame)
    return scaledMatrix


def detectOutliersWithDbscan(scaledMatrix):
    """Identifie les dossiers atypiques (bruit) avant la formation des pools de risque."""
    dbscanModel = DBSCAN(eps=config.DBSCAN_EPS, min_samples=config.DBSCAN_MIN_SAMPLES)
    dbscanLabels = dbscanModel.fit_predict(scaledMatrix)
    isOutlier = dbscanLabels == -1
    return isOutlier


def assignKmeansClusters(scaledMatrix, isOutlier):
    """Applique KMeans uniquement sur la population coeur (hors outliers DBSCAN)."""
    kmeansModel = KMeans(
        n_clusters=config.N_RISK_GRADES,
        random_state=config.RANDOM_SEED,
        n_init=config.KMEANS_N_INIT,
    )
    coreMatrix = scaledMatrix[~isOutlier]
    kmeansModel.fit(coreMatrix)

    if len(coreMatrix) > config.N_RISK_GRADES:
        silhouette = silhouette_score(coreMatrix, kmeansModel.labels_)
        print(f"[riskClustering] Silhouette score (population coeur, k={config.N_RISK_GRADES}) : {silhouette:.3f}")

    clusterIdRaw = np.full(scaledMatrix.shape[0], fill_value=-1, dtype=int)
    clusterIdRaw[~isOutlier] = kmeansModel.labels_
    return clusterIdRaw, kmeansModel


def mapClustersToOrderedRiskGrades(portfolioFrame, clusterIdRaw):
    """
    Classe les clusters par taux de defaut observe croissant et les associe
    aux etiquettes ordonnees (veryLow -> veryHigh). Les outliers DBSCAN
    (clusterIdRaw == -1) recoivent l'etiquette 'outlierReview'.
    """
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["clusterIdRaw"] = clusterIdRaw

    coreFrame = portfolioFrame[portfolioFrame["clusterIdRaw"] != -1]
    defaultRateByCluster = (
        coreFrame.groupby("clusterIdRaw")["defaultEverFlag"].mean().sort_values()
    )

    orderedClusterIds = defaultRateByCluster.index.tolist()
    clusterToGradeMap = {
        clusterId: config.RISK_GRADE_LABELS_ORDERED[rank]
        for rank, clusterId in enumerate(orderedClusterIds)
    }

    portfolioFrame["riskGradeClass"] = portfolioFrame["clusterIdRaw"].map(clusterToGradeMap)
    portfolioFrame["riskGradeClass"] = portfolioFrame["riskGradeClass"].fillna("outlierReview")

    print("[riskClustering] Taux de defaut ever (verite terrain, sert uniquement a ordonner les grades ;")
    print("[riskClustering] la PD calibree provient de pdCalibration.py / LRA) :")
    print(
        portfolioFrame.groupby("riskGradeClass")["defaultEverFlag"]
        .agg(["count", "mean"])
        .rename(columns={"count": "effectif", "mean": "tauxDefautObserve"})
        .to_string()
    )
    return portfolioFrame


def runRiskClustering(portfolioFrame):
    print("$" * 10)
    print("ETAPE 5 - CLUSTERING DU RISQUE (DBSCAN + KMEANS, PAS DE QUANTILES ARBITRAIRES)")
    print("$" * 10)

    scaledMatrix = prepareClusteringMatrix(portfolioFrame)
    isOutlier = detectOutliersWithDbscan(scaledMatrix)
    print(f"[riskClustering] Dossiers atypiques detectes par DBSCAN : {isOutlier.sum()} "
          f"({isOutlier.mean():.1%} du portefeuille) -> segment outlierReview")

    clusterIdRaw, _kmeansModel = assignKmeansClusters(scaledMatrix, isOutlier)
    portfolioFrame = mapClustersToOrderedRiskGrades(portfolioFrame, clusterIdRaw)

    return portfolioFrame
