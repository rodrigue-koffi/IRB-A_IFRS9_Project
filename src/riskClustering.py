"""
riskClustering.py
==================
Etape 6 : constitution des classes de RISQUE, a l'interieur de chaque
populationSegment produit a l'etape 5 (populationSegmentation.py). Une classe
de risque n'est ainsi jamais construite en melangeant des obligors de
capacite economique tres differente (cf. docstring de populationSegmentation.py) ;
le decoupage en classes homogenes de risque impose par l'Art. 170 CRR est
applique EN DEUX TEMPS : d'abord la population (etape 5), puis le risque
(cette etape), et non plus en un seul clustering global comme dans la
version precedente du pipeline.

Methode retenue, POUR CHAQUE populationSegment separement (les obligors du
segment "populationOutlierReview" ne sont pas re-segmentes par risque : ils
recoivent directement l'etiquette 'outlierReview', ils sont deja isoles pour
revue manuelle a l'etape 5) :

  1. ALGORITHME DE BELSON (segmentation binaire recursive, precurseur de
     CHAID/AID, Belson 1959) : contrairement au clustering non supervise
     (KMeans) utilise dans la version precedente, Belson est une methode
     SUPERVISEE - elle utilise le defaut observe (defaultEverFlag, seule
     verite terrain disponible au niveau obligor) pour choisir, a chaque
     noeud, la variable et le seuil qui separent le mieux les bons et
     mauvais payeurs (test du Chi2 d'independance sur la table de
     contingence 2x2 [gauche/droite] x [defaut/non-defaut]). L'arbre est
     construit iterativement jusqu'a une profondeur maximale
     (config.BELSON_MAX_DEPTH) ou jusqu'a ce qu'aucune coupure ne soit plus
     statistiquement significative (config.BELSON_CHI2_PVALUE_THRESHOLD),
     sous contrainte de taille minimale de feuille (config.BELSON_MIN_LEAF_SIZE).
     ATTENTION (a documenter en gouvernance des modeles) : parce que Belson
     utilise directement le defaut pour construire les classes, son pouvoir
     discriminant en echantillon (in-sample) est structurellement superieur
     a celui d'un clustering non supervise - c'est le prix a payer pour des
     classes plus homogenes, mais cela accroit aussi le risque de sur-
     apprentissage sur un historique limite (cf. modelValidation.py, le
     decoupage Train/OOT reste le garde-fou contre ce risque).

  2. FUSION DES FEUILLES : l'arbre produit un nombre variable de feuilles
     (jusqu'a 2^BELSON_MAX_DEPTH). Les feuilles sont triees par taux de
     defaut observe croissant, puis fusionnees deux a deux (la paire de
     feuilles ADJACENTES la plus proche en taux de defaut) jusqu'a obtenir
     exactement config.N_RISK_GRADES classes (ou moins si l'arbre n'a pas
     produit assez de feuilles), garantissant la monotonie du taux de
     defaut par construction (pas besoin de PAVA a ce stade, contrairement
     a l'ancienne version : la fusion respecte deja l'ordre).

  3. VALIDATION ANOVA : une fois les classes construites, une analyse de
     variance a un facteur (one-way ANOVA, scipy.stats.f_oneway) est menee
     sur le taux de defaut par classe, a l'interieur de chaque
     populationSegment, pour verifier explicitement l'exigence de l'Art. 170
     CRR : heterogeneite INTER-classe (les moyennes de classe doivent
     differer significativement, F eleve / p-value faible) et, par
     construction du test, homogeneite INTRA-classe (la variance residuelle
     "within" doit rester faible face a la variance "between"). Le eta2
     (part de variance expliquee par le decoupage en classes) est calcule en
     complement de la p-value, car avec un grand echantillon une p-value
     peut etre significative meme si l'effet est faible - eta2 donne une
     mesure de taille d'effet independante de la taille d'echantillon.
     Une seconde ANOVA (defaut ~ populationSegment) valide egalement,
     separement, que la segmentation de population elle-meme n'est pas
     neutre vis-a-vis du risque - resultat rapporte a titre diagnostique
     (populationSegmentation.py ne l'utilise pas pour se construire, il ne
     s'appuie que sur le revenu/la capacite economique, pas sur le defaut).
"""

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, f_oneway

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

TARGET_COLUMN = "defaultEverFlag"


# ------------------------------------------------------------------
# ALGORITHME DE BELSON (segmentation binaire recursive supervisee)
# ------------------------------------------------------------------

def _candidateThresholds(series):
    """
    Genere les seuils de coupure candidats pour une variable :
      - variable a faible cardinalite (<= BELSON_MAX_CANDIDATE_THRESHOLDS+1
        valeurs distinctes, typiquement les scores ordinaux) : chaque valeur
        distincte sauf la derniere ;
      - variable continue : quantiles regulierement espaces
        (config.BELSON_MAX_CANDIDATE_THRESHOLDS candidats), pour limiter le
        nombre de tests sans perdre la granularite utile a la decision.
    """
    uniqueValues = np.unique(series.dropna().values)
    if len(uniqueValues) <= 1:
        return []
    if len(uniqueValues) <= config.BELSON_MAX_CANDIDATE_THRESHOLDS + 1:
        return uniqueValues[:-1].tolist()

    quantileLevels = np.linspace(0, 1, config.BELSON_MAX_CANDIDATE_THRESHOLDS + 2)[1:-1]
    thresholds = np.unique(np.quantile(uniqueValues, quantileLevels))
    return thresholds.tolist()


def _evaluateSplit(nodeFrame, variable, threshold):
    """Calcule le Chi2 d'independance de la table de contingence 2x2
    [gauche <= seuil / droite > seuil] x [defaut / non-defaut]."""
    leftMask = nodeFrame[variable] <= threshold
    rightMask = ~leftMask

    leftSize, rightSize = int(leftMask.sum()), int(rightMask.sum())
    if leftSize < config.BELSON_MIN_LEAF_SIZE or rightSize < config.BELSON_MIN_LEAF_SIZE:
        return None

    contingencyTable = pd.crosstab(leftMask, nodeFrame[TARGET_COLUMN])
    if contingencyTable.shape != (2, 2):
        return None

    chi2Stat, pValue, _, _ = chi2_contingency(contingencyTable, correction=True)
    return {"variable": variable, "threshold": threshold, "chi2": chi2Stat, "pValue": pValue,
            "leftSize": leftSize, "rightSize": rightSize}


def _bestSplitForNode(nodeFrame, candidateVariables):
    """Cherche, parmi toutes les variables et tous les seuils candidats, la
    coupure qui MAXIMISE le Chi2 (association la plus forte avec le defaut) -
    critere de selection standard de l'algorithme de Belson/AID."""
    bestSplit = None
    for variable in candidateVariables:
        for threshold in _candidateThresholds(nodeFrame[variable]):
            candidate = _evaluateSplit(nodeFrame, variable, threshold)
            if candidate is None:
                continue
            if bestSplit is None or candidate["chi2"] > bestSplit["chi2"]:
                bestSplit = candidate
    return bestSplit


def growBelsonTree(nodeFrame, candidateVariables, depth=0, nodePath="root"):
    """
    Construit recursivement l'arbre de Belson et renvoie la liste des
    FEUILLES (dicts avec index des obligors, effectif, taux de defaut,
    chemin de regles). Chaque obligor appartient a exactement une feuille.
    """
    nObservations = len(nodeFrame)
    defaultRate = nodeFrame[TARGET_COLUMN].mean() if nObservations > 0 else np.nan

    canSplit = (
        depth < config.BELSON_MAX_DEPTH
        and nObservations >= 2 * config.BELSON_MIN_LEAF_SIZE
        and nodeFrame[TARGET_COLUMN].nunique() > 1
    )

    bestSplit = _bestSplitForNode(nodeFrame, candidateVariables) if canSplit else None

    if bestSplit is None or bestSplit["pValue"] >= config.BELSON_CHI2_PVALUE_THRESHOLD:
        return [{
            "path": nodePath,
            "index": nodeFrame.index,
            "size": nObservations,
            "defaultRate": defaultRate,
        }]

    leftMask = nodeFrame[bestSplit["variable"]] <= bestSplit["threshold"]
    leftFrame = nodeFrame[leftMask]
    rightFrame = nodeFrame[~leftMask]

    leftPath = f"{nodePath} | {bestSplit['variable']}<={bestSplit['threshold']:.3g} (chi2={bestSplit['chi2']:.1f}, p={bestSplit['pValue']:.4f})"
    rightPath = f"{nodePath} | {bestSplit['variable']}>{bestSplit['threshold']:.3g} (chi2={bestSplit['chi2']:.1f}, p={bestSplit['pValue']:.4f})"

    leftLeaves = growBelsonTree(leftFrame, candidateVariables, depth + 1, leftPath)
    rightLeaves = growBelsonTree(rightFrame, candidateVariables, depth + 1, rightPath)
    return leftLeaves + rightLeaves


def mergeLeavesIntoGrades(leaves, nGrades):
    """
    Trie les feuilles par taux de defaut croissant puis fusionne
    iterativement la paire de feuilles ADJACENTES la plus proche en taux de
    defaut jusqu'a obtenir au plus nGrades groupes. La monotonie du taux de
    defaut par groupe final est garantie par construction (fusion d'elements
    deja tries, jamais de permutation).
    """
    pools = sorted(
        [{"index": leaf["index"], "size": leaf["size"], "totalDefaults": leaf["defaultRate"] * leaf["size"]}
         for leaf in leaves],
        key=lambda p: (p["totalDefaults"] / p["size"]) if p["size"] > 0 else 0.0,
    )

    while len(pools) > nGrades:
        gapSizes = [
            abs((pools[i]["totalDefaults"] / max(pools[i]["size"], 1))
                - (pools[i + 1]["totalDefaults"] / max(pools[i + 1]["size"], 1)))
            for i in range(len(pools) - 1)
        ]
        mergeAt = int(np.argmin(gapSizes))
        mergedPool = {
            "index": pools[mergeAt]["index"].append(pools[mergeAt + 1]["index"]),
            "size": pools[mergeAt]["size"] + pools[mergeAt + 1]["size"],
            "totalDefaults": pools[mergeAt]["totalDefaults"] + pools[mergeAt + 1]["totalDefaults"],
        }
        pools = pools[:mergeAt] + [mergedPool] + pools[mergeAt + 2:]

    return pools


def assignGradeLabelsToPools(pools):
    """Associe chaque pool (deja trie par risque croissant) a une etiquette
    ordonnee. Si l'arbre produit moins de feuilles que N_RISK_GRADES, les
    etiquettes sont echantillonnees en conservant les extremes (veryLow et
    veryHigh) pour ne pas artificiellement resserrer l'echelle de risque."""
    nPools = len(pools)
    allLabels = config.RISK_GRADE_LABELS_ORDERED
    if nPools >= len(allLabels):
        chosenLabels = allLabels
    else:
        labelIndices = np.linspace(0, len(allLabels) - 1, nPools).round().astype(int)
        chosenLabels = [allLabels[i] for i in labelIndices]

    labelMap = {}
    for pool, label in zip(pools, chosenLabels):
        for obligorIndex in pool["index"]:
            labelMap[obligorIndex] = label
    return labelMap


def buildRiskGradesForPopulationSegment(segmentFrame):
    """Applique l'algorithme de Belson puis la fusion de feuilles a
    l'interieur d'UN SEUL populationSegment, et renvoie (labelMap, leaves,
    pools) pour tracabilite / reporting."""
    if segmentFrame[TARGET_COLUMN].nunique() <= 1 or len(segmentFrame) < 2 * config.BELSON_MIN_LEAF_SIZE:
        # Population trop petite ou sans variance de defaut observable :
        # repli explicite sur une classe unique (documente en limite).
        fallbackLabel = config.RISK_GRADE_LABELS_ORDERED[len(config.RISK_GRADE_LABELS_ORDERED) // 2]
        labelMap = {idx: fallbackLabel for idx in segmentFrame.index}
        leaves = [{"path": "root (repli - effectif/variance insuffisants)", "index": segmentFrame.index,
                   "size": len(segmentFrame), "defaultRate": segmentFrame[TARGET_COLUMN].mean()}]
        pools = [{"index": segmentFrame.index, "size": len(segmentFrame),
                  "totalDefaults": segmentFrame[TARGET_COLUMN].sum()}]
        return labelMap, leaves, pools

    leaves = growBelsonTree(segmentFrame, CLUSTERING_FEATURES)
    pools = mergeLeavesIntoGrades(leaves, config.N_RISK_GRADES)
    labelMap = assignGradeLabelsToPools(pools)
    return labelMap, leaves, pools


# ------------------------------------------------------------------
# VALIDATION ANOVA (homogeneite intra-classe / heterogeneite inter-classe)
# ------------------------------------------------------------------

def computeAnovaHomogeneity(frame, groupColumn, targetColumn=TARGET_COLUMN):
    """
    ANOVA a un facteur (scipy.stats.f_oneway) du taux de defaut par groupe.
    Renvoie F, p-value, eta2 (taille d'effet = SS_between / SS_total) et le
    nombre de groupes/observations utilises. eta2 proche de 0 = les groupes
    n'expliquent presque rien de la variance du defaut (classes peu
    homogenes/differenciees) ; proche de 1 = les groupes expliquent
    l'essentiel de la variance (tres bonne differenciation).
    """
    groups = [g[targetColumn].values for _, g in frame.groupby(groupColumn) if len(g) >= 2]
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return {"nGroups": len(groups), "nObs": len(frame), "fStat": np.nan, "pValue": np.nan, "etaSquared": np.nan}

    fStat, pValue = f_oneway(*groups)

    allValues = np.concatenate(groups)
    grandMean = allValues.mean()
    ssTotal = np.sum((allValues - grandMean) ** 2)
    ssBetween = np.sum([len(g) * (g.mean() - grandMean) ** 2 for g in groups])
    etaSquared = ssBetween / ssTotal if ssTotal > 0 else np.nan

    return {"nGroups": len(groups), "nObs": len(allValues), "fStat": fStat, "pValue": pValue, "etaSquared": etaSquared}


def runAnovaValidation(portfolioFrame):
    """
    Construit la table de validation ANOVA :
      - une ligne par populationSegment (homogeneite/heterogeneite des
        riskGradeClass A L'INTERIEUR de ce segment) ;
      - une ligne globale (heterogeneite des populationSegment entre eux,
        vis-a-vis du defaut - diagnostic complementaire).
    """
    records = []
    coreFrame = portfolioFrame[portfolioFrame["riskGradeClass"] != "outlierReview"]

    for segment in config.POPULATION_SEGMENT_LABELS_ORDERED:
        segmentFrame = coreFrame[coreFrame["populationSegment"] == segment]
        result = computeAnovaHomogeneity(segmentFrame, "riskGradeClass")
        result["perimetre"] = f"riskGradeClass au sein de {segment}"
        records.append(result)

    populationResult = computeAnovaHomogeneity(
        portfolioFrame[portfolioFrame["populationSegment"] != "populationOutlierReview"], "populationSegment"
    )
    populationResult["perimetre"] = "populationSegment (diagnostic, non utilise pour construire les classes)"
    records.append(populationResult)

    anovaTable = pd.DataFrame(records)[["perimetre", "nGroups", "nObs", "fStat", "pValue", "etaSquared"]]
    return anovaTable


# ------------------------------------------------------------------
# ORCHESTRATION ETAPE 6
# ------------------------------------------------------------------

def runRiskClustering(portfolioFrame):
    print("$" * 10)
    print("ETAPE 6 - CLASSES DE RISQUE PAR ALGORITHME DE BELSON (DANS CHAQUE POPULATION SEGMENT)")
    print("$" * 10)

    portfolioFrame = portfolioFrame.copy()
    riskGradeClass = pd.Series(index=portfolioFrame.index, dtype=object)
    belsonTreeSummaryRecords = []

    isPopulationOutlier = portfolioFrame["populationSegment"] == "populationOutlierReview"
    riskGradeClass.loc[isPopulationOutlier] = "outlierReview"

    for segment in config.POPULATION_SEGMENT_LABELS_ORDERED:
        segmentFrame = portfolioFrame[portfolioFrame["populationSegment"] == segment]
        labelMap, leaves, pools = buildRiskGradesForPopulationSegment(segmentFrame)

        for obligorIndex, label in labelMap.items():
            riskGradeClass.loc[obligorIndex] = label

        print(f"[riskClustering] {segment} ({len(segmentFrame)} obligors) : "
              f"arbre de Belson -> {len(leaves)} feuille(s) -> {len(pools)} classe(s) de risque")

        for leaf in leaves:
            belsonTreeSummaryRecords.append({
                "populationSegment": segment,
                "cheminDeRegles": leaf["path"],
                "effectif": leaf["size"],
                "tauxDefautFeuille": leaf["defaultRate"],
            })

    portfolioFrame["riskGradeClass"] = riskGradeClass
    belsonTreeSummary = pd.DataFrame(belsonTreeSummaryRecords)

    print("[riskClustering] Taux de defaut ever (verite terrain, sert uniquement a construire/ordonner les")
    print("[riskClustering] classes ; la PD calibree provient de pdCalibration.py / LRA) par population x grade :")
    print(
        portfolioFrame.groupby(["populationSegment", "riskGradeClass"])[TARGET_COLUMN]
        .agg(["count", "mean"])
        .rename(columns={"count": "effectif", "mean": "tauxDefautObserve"})
        .to_string()
    )

    anovaTable = runAnovaValidation(portfolioFrame)
    print("\n[riskClustering] VALIDATION ANOVA (Art. 170 CRR - homogeneite intra / heterogeneite inter-classe) :")
    for _, row in anovaTable.iterrows():
        if pd.isna(row["fStat"]):
            print(f"  - {row['perimetre']:<65} n/a (moins de 2 groupes exploitables)")
        else:
            verdict = "heterogeneite significative (OK)" if row["pValue"] < config.ANOVA_SIGNIFICANCE_LEVEL else "NON significative (a surveiller)"
            print(f"  - {row['perimetre']:<65} F={row['fStat']:.2f}  p={row['pValue']:.4f}  eta2={row['etaSquared']:.4f}  -> {verdict}")

    return portfolioFrame, anovaTable, belsonTreeSummary
