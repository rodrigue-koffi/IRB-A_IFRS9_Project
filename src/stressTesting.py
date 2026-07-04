"""
stressTesting.py
=================
Etape 13 : tests de stress (scenarios ponderes) et stress test inverse
(reverse stress test) - Art. 177 CRR (exigence de tests de resistance pour
les systemes de notation IRB) et guide EBA/BCE sur les methodologies de
stress testing.

Ce module etait absent de la premiere version modulaire (regression par
rapport au script original, Partie 6) : il est reintegre ici, en s'appuyant
sur la VRAIE formule de capital IRB (irbCapitalRwa.py) plutot que sur
l'approximation algebrique du script d'origine.

1) STRESS TESTS PAR SCENARIO :
   On rejoue le choc macroeconomique (taux de chomage) deja utilise dans
   ifrs9Staging.py pour la composante systemique de la PD Point-In-Time,
   sous 3 scenarios ponderes (Baseline/Upside/Downside), et on recalcule
   l'ECL du livre note (ACTIVE + DEFAULTED) sous chaque scenario.

2) STRESS TEST INVERSE :
   Plutot que de partir d'un scenario et de mesurer la perte qui en
   resulte, on part d'une perte limite (ici : le capital total requis —
   Pilier 1 + coussins — calcule au scenario central) et on cherche, par
   resolution numerique (bissection), le choc de chomage relatif au-dela
   duquel l'ECL du portefeuille depasse ce capital disponible. C'est la
   question inverse : "quel choc casse le coussin de capital de la
   banque ?" (EBA GL/2018/04 sur les tests de resistance inverses).
"""

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from src import config
from src.ifrs9Staging import MACRO_UNEMPLOYMENT_RATE, PIT_SENSITIVITY_BETA


def computeBaselineMacro():
    """Statistiques de la serie macro (memes valeurs que ifrs9Staging.py) et
    niveau courant a la date d'arrete."""
    values = list(MACRO_UNEMPLOYMENT_RATE.values())
    meanUnemployment = np.mean(values)
    stdUnemployment = np.std(values)
    observationYear = pd.Timestamp(config.OBSERVATION_DATE).year
    currentUnemployment = MACRO_UNEMPLOYMENT_RATE.get(observationYear, meanUnemployment)
    return currentUnemployment, meanUnemployment, stdUnemployment


def computeStressedEclForShock(ratedBook, unemploymentShock, currentUnemployment, meanUnemployment, stdUnemployment):
    """
    Recalcule l'ECL du livre note (ACTIVE+DEFAULTED) sous un choc de chomage
    relatif donne, en isolant l'effet INCREMENTAL du scenario par rapport au
    scenario central deja calibre dans pdCurrentPit/pdLifetime (etape 10).
    """
    stressedUnemployment = currentUnemployment * (1 + unemploymentShock)
    baselineDeltaMacro = (currentUnemployment - meanUnemployment) / stdUnemployment
    stressedDeltaMacro = (stressedUnemployment - meanUnemployment) / stdUnemployment

    macroShiftRatio = np.exp(PIT_SENSITIVITY_BETA * (stressedDeltaMacro - baselineDeltaMacro))

    pdPitStressed = (ratedBook["pdCurrentPit"] * macroShiftRatio).clip(0.0003, 0.999)
    pdLifetimeStressed = (ratedBook["pdLifetime"] * macroShiftRatio).clip(0.0003, 0.999)

    discountRate = config.RECOVERY_DISCOUNT_RATE_ANNUAL
    discountFactor12m = 1 / (1 + discountRate) ** 0.5
    discountFactorLifetime = 1 / (1 + discountRate) ** (ratedBook["remainingMonths"] / 12 / 2)

    ecl12mStressed = np.where(
        ratedBook["ifrs9Stage"] == 1,
        pdPitStressed * ratedBook["lgdDownturnEstimate"] * ratedBook["eadFinal"] * discountFactor12m,
        0.0,
    )
    eclLifetimeStressed = np.where(
        ratedBook["ifrs9Stage"].isin([2, 3]),
        pdLifetimeStressed * ratedBook["lgdDownturnEstimate"] * ratedBook["eadFinal"] * discountFactorLifetime,
        0.0,
    )
    eclTotalStressed = ecl12mStressed + eclLifetimeStressed
    return eclTotalStressed, pdPitStressed.mean()


def runScenarioStressTests(portfolioFrame):
    """Applique les 3 scenarios ponderes de config.STRESS_SCENARIOS."""
    ratedBook = portfolioFrame[portfolioFrame["ifrs9Stage"].notna()].copy()
    currentUnemployment, meanUnemployment, stdUnemployment = computeBaselineMacro()

    results = []
    for scenarioName, params in config.STRESS_SCENARIOS.items():
        eclStressedArray, pdMeanStressed = computeStressedEclForShock(
            ratedBook, params["unemploymentShock"], currentUnemployment, meanUnemployment, stdUnemployment
        )
        results.append({
            "scenario": scenarioName,
            "chocChomageRelatif": params["unemploymentShock"],
            "poidsScenario": params["weight"],
            "pdMoyenneStressee": pdMeanStressed,
            "eclTotaleStressee": eclStressedArray.sum(),
        })

    stressDf = pd.DataFrame(results)
    baselineEcl = stressDf.loc[stressDf["scenario"] == "Baseline", "eclTotaleStressee"].iloc[0]
    stressDf["variationEclVsBaselinePct"] = (stressDf["eclTotaleStressee"] / baselineEcl - 1) * 100
    stressDf["eclPondereeParScenario"] = stressDf["eclTotaleStressee"] * stressDf["poidsScenario"]

    return stressDf


def runReverseStressTest(portfolioFrame):
    """
    Recherche par bissection (scipy.optimize.brentq) du choc de chomage
    relatif au-dela duquel l'ECL totale du livre note depasse le capital
    total requis (Pilier 1 + coussins), calcule au scenario central.
    """
    ratedBook = portfolioFrame[portfolioFrame["ifrs9Stage"].notna()].copy()
    currentUnemployment, meanUnemployment, stdUnemployment = computeBaselineMacro()
    capitalAvailableProxy = portfolioFrame["totalCapitalRequired"].sum()

    def eclGapAtShock(unemploymentShock):
        eclStressedArray, _ = computeStressedEclForShock(
            ratedBook, unemploymentShock, currentUnemployment, meanUnemployment, stdUnemployment
        )
        return eclStressedArray.sum() - capitalAvailableProxy

    lowShock, highShock = 0.0, config.REVERSE_STRESS_SHOCK_SEARCH_MAX

    if eclGapAtShock(lowShock) >= 0:
        breakingShock = 0.0  # le capital est deja insuffisant au scenario central
    elif eclGapAtShock(highShock) < 0:
        breakingShock = np.nan  # pas de point de rupture trouve dans la plage testee
    else:
        breakingShock = brentq(eclGapAtShock, lowShock, highShock, xtol=1e-4)

    breakingUnemploymentRate = (
        currentUnemployment * (1 + breakingShock) if pd.notna(breakingShock) else np.nan
    )

    return {
        "capitalDisponibleProxy": capitalAvailableProxy,
        "chocChomageDeRupture": breakingShock,
        "tauxChomageDeRupturePct": breakingUnemploymentRate,
    }


def runStressTesting(portfolioFrame):
    print("=" * 80)
    print("ETAPE 13 - TESTS DE STRESS (SCENARIOS) ET STRESS TEST INVERSE - ART. 177 CRR")
    print("=" * 80)

    stressDf = runScenarioStressTests(portfolioFrame)
    print("[stressTesting] Resultats par scenario :")
    print(stressDf.to_string(index=False))

    reverseResult = runReverseStressTest(portfolioFrame)
    if pd.isna(reverseResult["chocChomageDeRupture"]):
        print("[stressTesting] Stress test inverse : aucun point de rupture trouve "
              f"dans la plage testee (0 a +{config.REVERSE_STRESS_SHOCK_SEARCH_MAX:.0%})")
    else:
        print(f"[stressTesting] Stress test inverse : choc de chomage de rupture = "
              f"+{reverseResult['chocChomageDeRupture']:.1%} "
              f"(taux de chomage de rupture simule ~ {reverseResult['tauxChomageDeRupturePct']:.2f}%)")
        print(f"[stressTesting] Capital disponible (proxy Pilier 1 + coussins) : "
              f"{reverseResult['capitalDisponibleProxy']:,.0f}")

    return stressDf, reverseResult
