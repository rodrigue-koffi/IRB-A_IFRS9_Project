"""
reporting.py
=============
Etape 15 : export des resultats vers un classeur Excel multi-onglets,
exploitable directement en Power BI / revue de comite des modeles.
"""

import pandas as pd
from src import config

EXPORT_COLUMNS = [
    "obligorId", "perimeterSegment", "vintageYear", "originationDate", "maturityDate",
    "bookStatusAsOfObservationDate", "monthsOnBookAtObservation",
    "age", "sex", "jobSkillLevel", "housingType", "purpose", "creditAmount", "durationMonths",
    "monthlyIncomeEur", "smeAnnualTurnoverEur",
    "populationSegment", "populationClusterIdRaw",
    "riskGradeClass",
    "pdLongRunAverageGrade", "mocCategoryA", "mocCategoryB", "mocCategoryC", "pdFinalRegulatory",
    "pdOriginationGrade", "pdCurrentPit", "pdLifetime",
    "lgdRealized", "lgdDownturnEstimate",
    "eadFinal", "ccfAssigned",
    "assetCorrelationR", "maturityAdjustmentFactor", "capitalRequirementK",
    "riskWeightedAssets", "smeSupportingFactorApplied", "pillar1CapitalRequirement", "totalCapitalRequired",
    "daysPastDue", "sicrFlag", "ifrs9Stage", "ecl12Month", "eclLifetime", "eclFinal",
    "firstYearDefaultFlag", "defaultEverFlag",
]


def buildGradeSummary(portfolioFrame):
    """Synthese par (populationSegment x riskGradeClass) - la cellule est
    desormais l'unite de notation, cf. pdCalibration.py."""
    return (
        portfolioFrame.groupby(["populationSegment", "riskGradeClass"])
        .agg(
            effectif=("obligorId", "count"),
            pdLongRunAverage=("pdLongRunAverageGrade", "mean"),
            pdFinaleReglementaire=("pdFinalRegulatory", "mean"),
            lgdDownturnMoyenne=("lgdDownturnEstimate", "mean"),
            eadTotale=("eadFinal", "sum"),
            rwaTotal=("riskWeightedAssets", "sum"),
        )
        .reset_index()
    )


def buildPopulationSummary(portfolioFrame):
    return (
        portfolioFrame.groupby("populationSegment")
        .agg(
            effectif=("obligorId", "count"),
            revenuMensuelMoyen=("monthlyIncomeEur", "mean"),
            qualificationMoyenne=("jobSkillLevel", "mean"),
            pdFinaleReglementaireMoyenne=("pdFinalRegulatory", "mean"),
            eadTotale=("eadFinal", "sum"),
            rwaTotal=("riskWeightedAssets", "sum"),
        )
        .reset_index()
    )


def buildStagingSummary(portfolioFrame):
    ratedBook = portfolioFrame[portfolioFrame["ifrs9Stage"].notna()]
    return (
        ratedBook.groupby("ifrs9Stage")
        .agg(
            effectif=("obligorId", "count"),
            eadTotale=("eadFinal", "sum"),
            eclTotale=("eclFinal", "sum"),
        )
        .reset_index()
    )


def buildMocDecomposition(portfolioFrame):
    return (
        portfolioFrame.groupby(["populationSegment", "riskGradeClass"])
        .agg(
            pdLongRunAverage=("pdLongRunAverageGrade", "mean"),
            mocCategorieA=("mocCategoryA", "mean"),
            mocCategorieB=("mocCategoryB", "mean"),
            mocCategorieC=("mocCategoryC", "mean"),
            pdFinaleReglementaire=("pdFinalRegulatory", "mean"),
        )
        .reset_index()
    )


def buildPerimeterSummary(portfolioFrame):
    return (
        portfolioFrame.groupby("perimeterSegment")
        .agg(
            effectif=("obligorId", "count"),
            eadTotale=("eadFinal", "sum"),
            rwaTotal=("riskWeightedAssets", "sum"),
            tauxDefautLra=("pdLongRunAverageGrade", "mean"),
        )
        .reset_index()
    )


def buildReverseStressSummary(reverseStressResult):
    return pd.DataFrame([{
        "capitalDisponibleProxy": reverseStressResult["capitalDisponibleProxy"],
        "chocChomageDeRupture": reverseStressResult["chocChomageDeRupture"],
        "tauxChomageDeRupturePct": reverseStressResult["tauxChomageDeRupturePct"],
    }])


def exportToExcel(portfolioFrame, annualTable, performancePanel, stressDf, reverseStressResult,
                   discriminationResults=None, vifTable=None, anovaTable=None, belsonTreeSummary=None,
                   fileName="Credit_Risk_IRB_IFRS9_sortie.xlsx"):
    outputPath = config.OUTPUT_DIR / fileName
    availableColumns = [c for c in EXPORT_COLUMNS if c in portfolioFrame.columns]

    with pd.ExcelWriter(outputPath, engine="openpyxl") as writer:
        portfolioFrame[availableColumns].to_excel(writer, sheet_name="DonneesObligors", index=False)
        buildGradeSummary(portfolioFrame).to_excel(writer, sheet_name="SyntheseParGrade", index=False)
        buildPopulationSummary(portfolioFrame).to_excel(writer, sheet_name="SyntheseParPopulation", index=False)
        buildMocDecomposition(portfolioFrame).to_excel(writer, sheet_name="DecompositionMoC", index=False)
        buildStagingSummary(portfolioFrame).to_excel(writer, sheet_name="SyntheseStagingIFRS9", index=False)
        buildPerimeterSummary(portfolioFrame).to_excel(writer, sheet_name="SyntheseParPerimetre", index=False)
        annualTable.to_excel(writer, sheet_name="SerieAnnuelleDefautLRA", index=False)
        performancePanel.to_excel(writer, sheet_name="PanelObservationsLRA", index=False)
        stressDf.to_excel(writer, sheet_name="StressTestsScenarios", index=False)
        buildReverseStressSummary(reverseStressResult).to_excel(writer, sheet_name="StressTestInverse", index=False)
        if discriminationResults is not None:
            discriminationResults.to_excel(writer, sheet_name="ValidationAucGiniTrainOot", index=False)
        if vifTable is not None:
            vifTable.to_excel(writer, sheet_name="ValidationVIF", index=False)
        if anovaTable is not None:
            anovaTable.to_excel(writer, sheet_name="ValidationANOVA", index=False)
        if belsonTreeSummary is not None:
            belsonTreeSummary.to_excel(writer, sheet_name="ArbreDeBelson", index=False)

    print(f"[reporting] Classeur Excel genere : {outputPath}")
    return outputPath


def runReporting(portfolioFrame, annualTable, performancePanel, stressDf, reverseStressResult,
                  discriminationResults=None, vifTable=None, anovaTable=None, belsonTreeSummary=None):
    print("=" * 80)
    print("ETAPE 15 - EXPORT DES RESULTATS (EXCEL MULTI-ONGLETS)")
    print("=" * 80)
    return exportToExcel(
        portfolioFrame, annualTable, performancePanel, stressDf, reverseStressResult,
        discriminationResults, vifTable, anovaTable, belsonTreeSummary,
    )


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
    from src.stressTesting import runStressTesting
    from src.modelValidation import runModelValidation
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
    stressDf, reverseResult = runStressTesting(portfolioFrame)
    discriminationResults, vifTable = runModelValidation(portfolioFrame, performancePanel)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputPath = runReporting(
        portfolioFrame, annualTable, performancePanel, stressDf, reverseResult,
        discriminationResults, vifTable, anovaTable, belsonTreeSummary,
    )
    print("\n[VERIFICATION] reporting.py OK")
    print(f"Fichier genere : {outputPath}")
