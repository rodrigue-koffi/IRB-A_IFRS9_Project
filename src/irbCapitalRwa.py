"""
irbCapitalRwa.py
=================
Etape 11  : calcul du capital reglementaire IRB-A selon la
VRAIE formule de Bale (Art. 153/154 CRR), et non la simplification
"12.5 * PD * LGD"  (qui n'est pas la formule reglementaire
- elle en omet la correlation d'actifs R, la fonction de repartition normale
et l'ajustement de maturite).

Formule generale (fonction de risque IRB) :

    K = LGD * [ N( sqrt(1/(1-R)) * G(PD) + sqrt(R/(1-R)) * G(0.999) ) - PD ] * MA

    RWA = K * 12.5 * EAD

ou N(.) est la fonction de repartition de la loi normale centree reduite,
G(.) son inverse, R la correlation d'actifs et MA l'ajustement de maturite
(uniquement pour les expositions Corporate/PME-Corporate, pas pour le Retail).

Correlation R :
  - Retail (Art. 154(1)) :
        R = 0.03*(1-e^-35*PD)/(1-e^-35) + 0.16*(1-(1-e^-35*PD)/(1-e^-35))
  - Corporate / PME-Corporate (Art. 153(1)), avec ajustement taille de firme
    pour les PME dont le CA S est compris entre 5 et 50 M EUR (Art. 153(4)) :
        R_corp = 0.12*(1-e^-50*PD)/(1-e^-50) + 0.24*(1-(1-e^-50*PD)/(1-e^-50))
        R_pme  = R_corp - 0.04 * (1 - (S_Meur - 5) / 45)

Ajustement de maturite (Corporate/PME-Corporate uniquement, Art. 162) :
        b  = (0.11852 - 0.05478 * ln(PD))^2
        MA = (1 + (M - 2.5) * b) / (1 - 1.5 * b),  M = duree residuelle en annees (bornee [1,5])

Facteur supportant PME (Art. 501 CRR) : applique un abattement de RWA
(config.SME_SUPPORTING_FACTOR) aux expositions PME dont le CA est <= 50 M EUR,
conformement a l'objectif de soutien au financement des PME.
"""

import numpy as np
from scipy.stats import norm
from src import config


def computeRetailCorrelation(pd_):
    expTerm = (1 - np.exp(-35 * pd_)) / (1 - np.exp(-35))
    return 0.03 * expTerm + 0.16 * (1 - expTerm)


def computeCorporateCorrelation(pd_):
    expTerm = (1 - np.exp(-50 * pd_)) / (1 - np.exp(-50))
    return 0.12 * expTerm + 0.24 * (1 - expTerm)


def applySmeFirmSizeAdjustment(correlation, turnoverEur):
    turnoverMeur = np.clip(turnoverEur / 1_000_000, config.SME_CORREL_TURNOVER_FLOOR_MEUR, config.SME_CORREL_TURNOVER_CAP_MEUR)
    adjustment = 0.04 * (1 - (turnoverMeur - config.SME_CORREL_TURNOVER_FLOOR_MEUR) / 45)
    return np.clip(correlation - adjustment, 0.0, 1.0)


def computeMaturityAdjustment(pd_, remainingMonths):
    maturityYears = np.clip(remainingMonths / 12, 1, 5)
    bFactor = (0.11852 - 0.05478 * np.log(pd_)) ** 2
    maturityAdjustment = (1 + (maturityYears - 2.5) * bFactor) / (1 - 1.5 * bFactor)
    return maturityAdjustment


def computeCapitalRequirementK(pd_, lgd, correlation, maturityAdjustment):
    gPd = norm.ppf(pd_)
    gConfidence = norm.ppf(0.999)
    conditionalPd = norm.cdf(np.sqrt(1 / (1 - correlation)) * gPd + np.sqrt(correlation / (1 - correlation)) * gConfidence)
    capitalK = lgd * (conditionalPd - pd_) * maturityAdjustment
    return np.clip(capitalK, 0.0, 1.0)


def runIrbCapitalRwa(portfolioFrame):
    print("$" * 15)
    print("ETAPE 11 - CAPITAL REGLEMENTAIRE IRB-A (FORMULE BALE COMPLETE, ART. 153/154 CRR)")
    print("$" * 10)

    portfolioFrame = portfolioFrame.copy()
    pdForCapital = portfolioFrame["pdFinalRegulatory"].clip(0.0003, 0.999)  # PD TTC/LRA+MoC, pas la PD PIT (Art.180(2))
    lgdForCapital = portfolioFrame["lgdDownturnEstimate"].fillna(portfolioFrame["lgdDownturnEstimate"].median())

    isCorporateSme = portfolioFrame["perimeterSegment"] == "CORPORATE_SME"

    retailCorrelation = computeRetailCorrelation(pdForCapital)
    corporateCorrelation = computeCorporateCorrelation(pdForCapital)
    corporateCorrelationAdjusted = applySmeFirmSizeAdjustment(
        corporateCorrelation, portfolioFrame["smeAnnualTurnoverEur"].fillna(config.SME_TURNOVER_MAX_EUR)
    )

    correlation = np.where(isCorporateSme, corporateCorrelationAdjusted, retailCorrelation)

    maturityAdjustment = np.where(
        isCorporateSme,
        computeMaturityAdjustment(pdForCapital, portfolioFrame["remainingMonths"].fillna(12)),
        1.0,  # pas d'ajustement de maturite pour le Retail (Art. 154)
    )

    capitalK = computeCapitalRequirementK(pdForCapital, lgdForCapital, correlation, maturityAdjustment)

    portfolioFrame["assetCorrelationR"] = correlation
    portfolioFrame["maturityAdjustmentFactor"] = maturityAdjustment
    portfolioFrame["capitalRequirementK"] = capitalK
    portfolioFrame["riskWeightedAssets"] = capitalK * 12.5 * portfolioFrame["eadFinal"]

    # Facteur supportant PME - Art. 501 CRR
    isSmeSupportable = portfolioFrame["perimeterSegment"].isin(["RETAIL_SME", "CORPORATE_SME"]) & (
        portfolioFrame["smeAnnualTurnoverEur"].fillna(0) <= config.SME_TURNOVER_MAX_EUR
    )
    portfolioFrame["smeSupportingFactorApplied"] = np.where(isSmeSupportable, config.SME_SUPPORTING_FACTOR, 1.0)
    portfolioFrame["riskWeightedAssets"] = portfolioFrame["riskWeightedAssets"] * portfolioFrame["smeSupportingFactorApplied"]

    portfolioFrame["pillar1CapitalRequirement"] = portfolioFrame["riskWeightedAssets"] * config.PILLAR1_MIN_CAPITAL_RATIO
    portfolioFrame["capitalConservationBuffer"] = portfolioFrame["riskWeightedAssets"] * config.CAPITAL_CONSERVATION_BUFFER
    portfolioFrame["ccybBuffer"] = portfolioFrame["riskWeightedAssets"] * config.CCYB_BUFFER
    portfolioFrame["totalCapitalRequired"] = (
        portfolioFrame["pillar1CapitalRequirement"] + portfolioFrame["capitalConservationBuffer"] + portfolioFrame["ccybBuffer"]
    )

    print(f"[irbCapitalRwa] RWA total : {portfolioFrame['riskWeightedAssets'].sum():,.0f}")
    print(f"[irbCapitalRwa] Exigence Pilier 1 (8%) : {portfolioFrame['pillar1CapitalRequirement'].sum():,.0f}")
    print(f"[irbCapitalRwa] Capital total requis (P1 + coussins) : {portfolioFrame['totalCapitalRequired'].sum():,.0f}")
    print(f"[irbCapitalRwa] Correlation moyenne appliquee : {np.mean(correlation):.4f}")

    return portfolioFrame
