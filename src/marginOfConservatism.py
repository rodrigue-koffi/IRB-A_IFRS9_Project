"""
marginOfConservatism.py
========================
Etape 7 : Marge de Conservatisme (MoC), second point souleve
lors de l'entretien technique ("vous n'avez pas utilise les MoC A, B, C").

 Selon l'EBA GL/2017/16 (par. 41-52), la marge de conservatisme est un ADD-ON
ADDITIF applique a la PD Long Run Average pour couvrir les sources
d'incertitude residuelle, decompose en trois categories :

  Categorie A - Erreur d'estimation generale : incertitude statistique liee
      a la taille de l'echantillon utilise pour estimer la PD LRA (plus le
      nombre d'observations/defauts par grade est faible, plus la marge est
      elevee). Implementee ici via un intervalle de confiance de Wilson.

  Categorie B - Deficiences de donnees ou de methode identifiees : ici,
      donnees temporelles simulees, revenu proxy, notation par clustering
      non supervise plutot que par jugement d'expert valide. Ajout
      forfaitaire documente (config.MOC_B_FLAT_ADDON)
      
  Categorie C - Changements pertinents non encore refletes dans la LRA :
      changement de politique d'octroi, de perimetre ou de contexte
      economique depuis la periode de calibration. Approche ici via un
      indice de stabilite de population (PSI) entre la distribution des
      grades sur l'historique et sur le millesime le plus recent : un PSI
      eleve signale un changement de mix de risque non capture par la LRA.

PD finale reglementaire = PD_LRA + MoC_A + MoC_B + MoC_C (Art. 179(1)(f) CRR :
"marge de conservatisme appropriee liee a la plage attendue d'erreurs
d'estimation").
"""

import numpy as np
import pandas as pd
from scipy import stats
from src import config


def computeMocCategoryA(annualTable, lraByGrade):
    """
    MoC A : demi-largeur superieure de l'intervalle de confiance de Wilson
    sur le taux de defaut agrege du grade, au niveau de confiance
    config.MOC_A_CONFIDENCE_LEVEL, au-dela du point central (LRA).
    """
    aggregated = (
        annualTable.groupby("riskGradeClass")
        .apply(lambda g: pd.Series({
            "totalObservations": g["observationCount"].sum(),
            "totalDefaults": (g["annualDefaultRate"] * g["observationCount"]).sum(),
        }))
        .reset_index()
    )

    zScore = stats.norm.ppf(1 - (1 - config.MOC_A_CONFIDENCE_LEVEL) / 2)
    mocARecords = []
    for _, row in aggregated.iterrows():
        n = max(row["totalObservations"], 1)
        p = row["totalDefaults"] / n
        # Intervalle de Wilson (plus robuste que Wald pour des p petits / n modeste)
        denominator = 1 + (zScore ** 2) / n
        centre = (p + (zScore ** 2) / (2 * n)) / denominator
        halfWidth = (zScore * np.sqrt((p * (1 - p) / n) + (zScore ** 2) / (4 * n ** 2))) / denominator
        upperBound = centre + halfWidth

        pdLra = lraByGrade.get(row["riskGradeClass"], p)
        mocA = max(upperBound - pdLra, 0.0)
        mocARecords.append({"riskGradeClass": row["riskGradeClass"], "mocCategoryA": mocA})

    return pd.DataFrame(mocARecords).set_index("riskGradeClass")["mocCategoryA"]


def computeMocCategoryB():
    """
    MoC B : add-on forfaitaire pour deficiences de donnees/methode
    identifiees et documentees (cf. docstring du module et docs/METHODOLOGY.md).
    Applique uniformement a tous les grades : une deficience de donnees
    affecte l'ensemble du perimetre, pas un grade en particulier.
    """
    return config.MOC_B_FLAT_ADDON


def computePopulationStabilityIndex(referenceDistribution, currentDistribution, epsilon=1e-4):
    """PSI standard : somme((current - reference) * ln(current/reference))."""
    reference = referenceDistribution.reindex(currentDistribution.index).fillna(epsilon).clip(lower=epsilon)
    current = currentDistribution.fillna(epsilon).clip(lower=epsilon)
    psiValue = np.sum((current - reference) * np.log(current / reference))
    return psiValue


def computeMocCategoryC(portfolioFrame):
    """
    MoC C : compare la distribution des grades sur l'historique (tous
    millesimes sauf le plus recent) a celle du millesime le plus recent.
    Si le PSI global depasse le seuil d'alerte, un add-on proportionnel est
    applique a tous les grades (signal de changement de mix de risque /
    de politique d'octroi non encore reflete dans la LRA).
    """
    mostRecentVintage = portfolioFrame["vintageYear"].max()
    historicalMask = portfolioFrame["vintageYear"] < mostRecentVintage

    referenceDistribution = portfolioFrame.loc[historicalMask, "riskGradeClass"].value_counts(normalize=True)
    currentDistribution = portfolioFrame.loc[~historicalMask, "riskGradeClass"].value_counts(normalize=True)

    psiValue = computePopulationStabilityIndex(referenceDistribution, currentDistribution)
    print(f"[marginOfConservatism] PSI distribution des grades (dernier millesime vs historique) : {psiValue:.4f}")

    if psiValue > config.MOC_C_PSI_ALERT_THRESHOLD:
        mocC = 0.10 * psiValue  # add-on proportionnel au signal de derive, plafonne implicitement par le PSI lui-meme
        print(f"[marginOfConservatism] PSI > seuil d'alerte ({config.MOC_C_PSI_ALERT_THRESHOLD}) -> MoC C active = {mocC:.4%}")
    else:
        mocC = 0.0
        print(f"[marginOfConservatism] PSI sous le seuil d'alerte -> MoC C = 0")

    return mocC


def runMarginOfConservatism(portfolioFrame, annualTable, lraByGrade):
    print("=" * 80)
    print("ETAPE 7 - MARGE DE CONSERVATISME (MoC A / B / C) - EBA GL/2017/16")
    print("=" * 80)

    mocASeries = computeMocCategoryA(annualTable, lraByGrade)
    mocBFlat = computeMocCategoryB()
    mocCFlat = computeMocCategoryC(portfolioFrame)

    portfolioFrame = portfolioFrame.copy()
    portfolioFrame["mocCategoryA"] = portfolioFrame["riskGradeClass"].map(mocASeries).fillna(0.0)
    portfolioFrame["mocCategoryB"] = mocBFlat
    portfolioFrame["mocCategoryC"] = mocCFlat

    portfolioFrame["pdFinalRegulatory"] = (
        portfolioFrame["pdLongRunAverageGrade"]
        + portfolioFrame["mocCategoryA"]
        + portfolioFrame["mocCategoryB"]
        + portfolioFrame["mocCategoryC"]
    ).clip(upper=0.999, lower=0.0003)

    summaryByGrade = portfolioFrame.groupby("riskGradeClass").agg(
        pdLongRunAverageGrade=("pdLongRunAverageGrade", "mean"),
        mocCategoryA=("mocCategoryA", "mean"),
        mocCategoryB=("mocCategoryB", "mean"),
        mocCategoryC=("mocCategoryC", "mean"),
        pdFinalRegulatory=("pdFinalRegulatory", "mean"),
    )
    print("[marginOfConservatism] Decomposition PD finale = LRA + MoC A + MoC B + MoC C, par grade :")
    print(summaryByGrade.applymap(lambda x: f"{x:.4%}").to_string())

    return portfolioFrame
