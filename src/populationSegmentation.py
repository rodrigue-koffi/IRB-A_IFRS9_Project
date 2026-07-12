"""
populationSegmentation.py
==========================
Etape 5 : segmentation de la POPULATION en groupes homogenes de capacite
economique, AVANT toute notation de risque.

Pourquoi cette etape existe (et pourquoi elle est distincte de riskClustering.py) :
un obligor avec un revenu confortable et un obligor au revenu proche du
minimum ne relevent pas du meme univers statistique. Les entrainer dans le
meme modele de PD reviendrait a estimer une seule loi de probabilite sur une
population non homogene : les coefficients/centres appris seraient tires
vers la moyenne et ne representeraient correctement ni l'un ni l'autre
sous-groupe. C'est une consequence directe de l'exigence d'homogeneite
intra-classe de l'Art. 170 CRR, appliquee ici en amont de la notation de
risque plutot qu'au moment de la notation elle-meme (cf. riskClustering.py,
etape 6, qui applique l'algorithme de Belson SEPAREMENT dans chaque
populationSegment produit ici).

Methode retenue (meme logique defensive que riskClustering.py) :
  1. DBSCAN sur les variables de capacite economique standardisees ->
     detection des profils atypiques (revenu/ratio d'endettement
     incoherents), isoles en populationOutlierReview et exclus du KMeans.
  2. KMeans (k=config.N_POPULATION_SEGMENTS) sur la population coeur ->
     regroupement en pools homogenes de capacite economique.
  3. Les clusters bruts n'ont pas d'ordre intrinseque : ils sont classes par
     revenu mensuel moyen croissant, puis mappes vers les etiquettes
     ordonnees config.POPULATION_SEGMENT_LABELS_ORDERED (populationModeste
     -> populationAisee).

Variables utilisees : uniquement des variables connues a l'octroi et
representatives de la CAPACITE ECONOMIQUE de l'obligor (revenu, qualification
professionnelle, ratios d'endettement) - pas de variable de risque pur
(type de logement, epargne...) qui sera, elle, traitee a l'etape 6.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

from src import config

POPULATION_SEGMENTATION_FEATURES = [
    "monthlyIncomeEur",
    "jobSkillLevel",
    "creditToAnnualIncomeRatio",
    "installmentToIncomeRatio",
]


def preparePopulationMatrix(portfolioFrame):
    """Selectionne et standardise les variables de capacite economique."""
    featureFrame = portfolioFrame[POPULATION_SEGMENTATION_FEATURES].copy()
    featureFrame = featureFrame.replace([np.inf, -np.inf], np.nan)
    featureFrame = featureFrame.fillna(featureFrame.median(numeric_only=True))

    scaler = StandardScaler()
    scaledMatrix = scaler.fit_transform(featureFrame)
    return scaledMatrix


def detectPopulationOutliers(scaledMatrix):
    """Identifie les profils economiques atypiques avant la formation des populations."""
    dbscanModel = DBSCAN(eps=config.POPULATION_DBSCAN_EPS, min_samples=config.POPULATION_DBSCAN_MIN_SAMPLES)
    dbscanLabels = dbscanModel.fit_predict(scaledMatrix)
    isOutlier = dbscanLabels == -1
    return isOutlier


def assignPopulationClusters(scaledMatrix, isOutlier):
    """Applique KMeans uniquement sur la population coeur (hors outliers DBSCAN)."""
    kmeansModel = KMeans(
        n_clusters=config.N_POPULATION_SEGMENTS,
        random_state=config.RANDOM_SEED,
        n_init=config.POPULATION_KMEANS_N_INIT,
    )
    coreMatrix = scaledMatrix[~isOutlier]
    kmeansModel.fit(coreMatrix)

    if len(coreMatrix) > config.N_POPULATION_SEGMENTS:
        silhouette = silhouette_score(coreMatrix, kmeansModel.labels_)
        print(f"[populationSegmentation] Silhouette score (population coeur, k={config.N_POPULATION_SEGMENTS}) : {silhouette:.3f}")

    clusterIdRaw = np.full(scaledMatrix.shape[0], fill_value=-1, dtype=int)
    clusterIdRaw[~isOutlier] = kmeansModel.labels_
    return clusterIdRaw


def mapClustersToOrderedPopulationSegments(portfolioFrame, clusterIdRaw):
    """
    Classe les clusters par revenu mensuel moyen croissant et les associe
    aux etiquettes ordonnees (populationModeste -> populationAisee). Les
    outliers DBSCAN (clusterIdRaw == -1) recoivent l'etiquette
    'populationOutlierReview'.
    """
    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["populationClusterIdRaw"] = clusterIdRaw

    coreFrame = portfolioFrame[portfolioFrame["populationClusterIdRaw"] != -1]
    incomeByCluster = (
        coreFrame.groupby("populationClusterIdRaw")["monthlyIncomeEur"].mean().sort_values()
    )

    orderedClusterIds = incomeByCluster.index.tolist()
    clusterToSegmentMap = {
        clusterId: config.POPULATION_SEGMENT_LABELS_ORDERED[rank]
        for rank, clusterId in enumerate(orderedClusterIds)
    }

    portfolioFrame["populationSegment"] = portfolioFrame["populationClusterIdRaw"].map(clusterToSegmentMap)
    portfolioFrame["populationSegment"] = portfolioFrame["populationSegment"].fillna("populationOutlierReview")
    return portfolioFrame


def runPopulationSegmentation(portfolioFrame):
    print("$" * 10)
    print("ETAPE 5 - SEGMENTATION DE LA POPULATION (DBSCAN + KMEANS SUR LA CAPACITE ECONOMIQUE)")
    print("$" * 10)

    scaledMatrix = preparePopulationMatrix(portfolioFrame)
    isOutlier = detectPopulationOutliers(scaledMatrix)
    print(f"[populationSegmentation] Profils economiques atypiques detectes par DBSCAN : {isOutlier.sum()} "
          f"({isOutlier.mean():.1%} du portefeuille) -> populationOutlierReview")

    clusterIdRaw = assignPopulationClusters(scaledMatrix, isOutlier)
    portfolioFrame = mapClustersToOrderedPopulationSegments(portfolioFrame, clusterIdRaw)

    summary = (
        portfolioFrame.groupby("populationSegment")
        .agg(
            effectif=("obligorId", "count"),
            revenuMensuelMoyen=("monthlyIncomeEur", "mean"),
            qualificationMoyenne=("jobSkillLevel", "mean"),
            ratioEndettementMoyen=("creditToAnnualIncomeRatio", "mean"),
        )
        .reindex(config.POPULATION_SEGMENT_LABELS_ORDERED + ["populationOutlierReview"])
        .dropna(how="all")
    )
    print("[populationSegmentation] Profil economique par population (revenu croissant) :")
    print(summary.to_string())

    return portfolioFrame
