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
    5. riskClustering              -> classes de risque par DBSCAN + KMeans
    6. pdCalibration                -> PD Long Run Average (LRA, panel multi-annees)
    7. marginOfConservatism         -> Marge de Conservatisme (MoC A/B/C)
    8. lgdEstimation                -> LGD workout (couts + recouvrements)
    9. eadEstimation                 -> EAD (amortissement + CCF)
   10. ifrs9Staging                  -> PD PIT, SICR, staging, ECL
   11. irbCapitalRwa                  -> RWA / capital reglementaire (formule Bale complete)
   12. stressTesting                   -> scenarios + stress test inverse
   13. modelValidation                    -> Train/OOT, AUC, Gini, VIF
   14. reporting                        -> export Excel multi-onglets

Aucune dependance a la librairie `logging` : la tracabilite d'execution
passe par des impressions structurees (print), a l'image du script d'origine.
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
    print("=" * 80)
    print("PROJET RISQUE DE CREDIT - IRB-A / IFRS9 / CRR2-CRR3")
    print("Auteur : Rodrigue KOFFI")
    print("=" * 80)

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    portfolioFrame = dataIngestion.runDataIngestion()
    portfolioFrame = perimeterDefinition.runPerimeterDefinition(portfolioFrame)
    portfolioFrame, performancePanel = Tcg.runTemporalChronologyGeneration(portfolioFrame)
    portfolioFrame = featureEngineering.runFeatureEngineering(portfolioFrame)
    portfolioFrame = riskClustering.runRiskClustering(portfolioFrame)
    portfolioFrame, annualTable, lraByGrade = pdCalibration.runPdCalibration(portfolioFrame, performancePanel)
    portfolioFrame = marginOfConservatism.runMarginOfConservatism(portfolioFrame, annualTable, lraByGrade)
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
        discriminationResults, vifTable,
    )

    print("\n" + "=" * 80)
    print("FIN DU PIPELINE")
    print("=" * 80)
    return portfolioFrame


if __name__ == "__main__":
    runFullPipeline()
