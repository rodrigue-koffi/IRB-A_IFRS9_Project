"""
pipeline.py
===========
Auteur : Rodrigue KOFFI
PROJET RISQUE DE CREDIT - IRB-A / IFRS9 / CRR2-CRR3 (version modulaire)

Orchestrateur du pipeline, module par module, dans l'ordre CHRONOLOGIQUE du
cycle de vie d'un credit :

    1. dataIngestion               -> chargement / normalisation de la base brute
    2. perimeterDefinition         -> perimetre Retail / PME / Corporate-SME
    3. Tcg                         -> dates d'octroi/defaut, statut a l'arrete, panel LRA
    4. featureEngineering          -> variables de risque connues a l'octroi
    5. populationSegmentation      -> populations homogenes de capacite economique (DBSCAN + KMeans)
    6. riskClustering              -> classes de risque par algorithme de Belson, DANS chaque population
    7. pdCalibration                -> PD Long Run Average (LRA, credibilite de Buhlmann, panel multi-annees)
    8. marginOfConservatism         -> Marge de Conservatisme (MoC A/B/C)
    9. lgdEstimation                -> LGD workout (couts + recouvrements)
   10. eadEstimation                 -> EAD (amortissement + CCF)
   11. ifrs9Staging                  -> PD PIT, SICR, staging, ECL
   12. irbCapitalRwa                  -> RWA / capital reglementaire (formule Bale complete)
   13. stressTesting                   -> scenarios + stress test inverse
   14. modelValidation                    -> Train/OOT, AUC, Gini, VIF, ANOVA
   15. reporting                        -> export Excel multi-onglets

La segmentation de risque est desormais construite en DEUX temps distincts
(etapes 5 et 6, cf. docstrings respectifs) plutot qu'en un seul clustering
global : d'abord la population (capacite economique), puis le risque
(algorithme de Belson, supervise par le defaut) A L'INTERIEUR de chaque
population. Cf. docs/METHODOLOGY.md et docs/METHODOLOGY_SANS_FORMULES.md
pour la justification complete.

la tracabilite d'execution
passe par des impressions structurees (print)
"""

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import config
from src import dataIngestion
from src import perimeterDefinition
from src import Tcg
from src import featureEngineering
from src import populationSegmentation
from src import riskClustering
from src import pdCalibration
from src import marginOfConservatism
from src import lgdEstimation
from src import eadEstimation
from src import ifrs9Staging
from src import irbCapitalRwa
from src import stressTesting
from src import modelValidation
from src import reporting


def runFullPipeline():
    print("$" * 15)
    print("PROJET RISQUE DE CREDIT - IRB-A / IFRS9 / CRR2-CRR3")
    print("Auteur : Rodrigue KOFFI")


    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    portfolioFrame = dataIngestion.runDataIngestion()
    portfolioFrame = perimeterDefinition.runPerimeterDefinition(portfolioFrame)
    portfolioFrame, performancePanel = Tcg.runTemporalChronologyGeneration(portfolioFrame)
    portfolioFrame = featureEngineering.runFeatureEngineering(portfolioFrame)
    portfolioFrame = populationSegmentation.runPopulationSegmentation(portfolioFrame)
    portfolioFrame, anovaTable, belsonTreeSummary = riskClustering.runRiskClustering(portfolioFrame)
    portfolioFrame, annualTable, lraByCell = pdCalibration.runPdCalibration(portfolioFrame, performancePanel)
    portfolioFrame = marginOfConservatism.runMarginOfConservatism(portfolioFrame, annualTable, lraByCell)
    portfolioFrame = lgdEstimation.runLgdEstimation(portfolioFrame)
    portfolioFrame = eadEstimation.runEadEstimation(portfolioFrame)
    portfolioFrame = ifrs9Staging.runIfrs9Staging(portfolioFrame)
    portfolioFrame = irbCapitalRwa.runIrbCapitalRwa(portfolioFrame)
    stressDf, reverseStressResult = stressTesting.runStressTesting(portfolioFrame)
    discriminationResults, vifTable = modelValidation.runModelValidation(portfolioFrame, performancePanel)

    processedPath = config.DATA_PROCESSED_DIR / "portfolio_final.parquet"
    try:
        portfolioFrame.to_parquet(processedPath, index=False)
    except Exception:
        portfolioFrame.to_csv(config.DATA_PROCESSED_DIR / "portfolio_final.csv", index=False)

    reporting.runReporting(
        portfolioFrame, annualTable, performancePanel, stressDf, reverseStressResult,
        discriminationResults, vifTable, anovaTable, belsonTreeSummary,
    )

    print("\n" + "$" * 15)
    print("FIN DU PIPELINE")
    print("$" * 15)
    return portfolioFrame


if __name__ == "__main__":
    runFullPipeline()
