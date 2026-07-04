# Projet Risque de Crédit — IRB-A / IFRS 9 / CRR2-CRR3

**Auteur :** Rodrigue KOFFI

Pipeline Python modulaire de notation interne (IRB-A) et de provisionnement IFRS 9, construit à partir du jeu de données German Credit Data, retraité pour simuler un cycle de vie de crédit réaliste (chronologie, périmètre Retail/PME, coûts de recouvrement, tests de stress).

Ce projet reconstruit un premier script de notation en un pipeline modulaire, chronologique et documenté : calibration de la PD en Long Run Average sur un panel d'observations multi-années, Marge de Conservatisme conforme à l'EBA GL/2017/16 (catégories A/B/C), et fenêtre de performance à 12 mois évaluée à chaque anniversaire du crédit plutôt qu'une seule fois à l'octroi.

## Structure

```
IRB_IFRS9_Project/
├── data/
│   ├── raw/german_credit_data.xlsx         # donnée source (Kaggle / Statlog German Credit)
│   └── processed/                          # sorties intermédiaires (parquet/csv)
├── src/
│   ├── config.py                           # constantes et hypothèses centralisées
│   ├── dataIngestion.py                    # étape 1 : chargement / normalisation
│   ├── perimeterDefinition.py              # étape 2 : périmètre Retail / PME / Corporate-SME
│   ├── Tcg.py                              # étape 3 : dates octroi/défaut, panel d'observations LRA
│   ├── featureEngineering.py               # étape 4 : variables de risque à l'octroi
│   ├── riskClustering.py                   # étape 5 : DBSCAN + KMeans -> grades de risque
│   ├── pdCalibration.py                    # étape 6 : PD Long Run Average (panel multi-années)
│   ├── marginOfConservatism.py             # étape 7 : MoC A / B / C
│   ├── lgdEstimation.py                    # étape 8 : LGD workout (coûts + recouvrements)
│   ├── eadEstimation.py                    # étape 9 : EAD + CCF
│   ├── ifrs9Staging.py                     # étape 10 : PD PIT, SICR, staging, ECL
│   ├── irbCapitalRwa.py                    # étape 11 : RWA/capital (formule Bâle complète)
│   ├── stressTesting.py                    # étape 12 : scénarios de stress + stress test inverse
│   ├── modelValidation.py                  # étape 13 : Train/OOT, AUC, Gini, VIF
│   └── reporting.py                        # étape 14 : export Excel multi-onglets
├── docs/
│   └── METHODOLOGY.md                      # formules, justifications, articles CRR/CRD/EBA
├── sourcesGuidelines/                      # Guidelines EBA officielles citées (PD/LGD, downturn LGD, défaut, stress testing)
├── PresentationPDF/                        # support de présentation du projet (PDF)
├── output/                                 # classeur Excel de sortie
├── pipeline.py                             # orchestrateur (point d'entrée)
└── requirements.txt
```

## Exécution

```bash
pip install -r requirements.txt
python pipeline.py
```

Le classeur `output/Credit_Risk_IRB_IFRS9_sortie.xlsx` est généré avec les onglets : données obligors, synthèse par grade, décomposition MoC, synthèse staging IFRS 9, synthèse par périmètre, série annuelle de défaut (LRA), panel brut d'observations LRA, résultats des tests de stress par scénario, résultat du stress test inverse, validation AUC/Gini Train/OOT, VIF des variables de segmentation.

## Avertissement

Certaines données (dates, périmètre PME/Corporate, revenus, flux de recouvrement) sont **simulées** : le jeu de données source ne les contient pas. Détail dans `docs/METHODOLOGY.md`.
