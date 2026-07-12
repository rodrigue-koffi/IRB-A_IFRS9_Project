# Projet Risque de Crédit — IRB-A / IFRS 9 / CRR2-CRR3

**Auteur :** Rodrigue KOFFI

Pipeline Python modulaire de notation interne (IRB-A) et de provisionnement IFRS 9, construit à partir du jeu de données German Credit Data, retraité pour simuler un cycle de vie de crédit réaliste (chronologie, périmètre Retail/PME, coûts de recouvrement, tests de stress).



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
│   ├── populationSegmentation.py           # étape 5 : DBSCAN + KMeans -> populations homogènes (capacité économique)
│   ├── riskClustering.py                   # étape 6 : algorithme de Belson + ANOVA -> grades de risque, DANS chaque population
│   ├── pdCalibration.py                    # étape 7 : PD Long Run Average (crédibilité de Bühlmann, panel multi-années)
│   ├── marginOfConservatism.py             # étape 8 : MoC A / B / C
│   ├── lgdEstimation.py                    # étape 9 : LGD workout (coûts + recouvrements)
│   ├── eadEstimation.py                    # étape 10 : EAD + CCF
│   ├── ifrs9Staging.py                     # étape 11 : PD PIT, SICR, staging, ECL
│   ├── irbCapitalRwa.py                    # étape 12 : RWA/capital (formule Bâle complète)
│   ├── stressTesting.py                    # étape 13 : scénarios de stress + stress test inverse
│   ├── modelValidation.py                  # étape 14 : Train/OOT, AUC, Gini, VIF, ANOVA
│   └── reporting.py                        # étape 15 : export Excel multi-onglets
├── docs/
│   ├── METHODOLOGY.md                      # formules, justifications, articles CRR/CRD/EBA
│   └── METHODOLOGY_SANS_FORMULES.md        # même méthodologie, sans formule, pour un lecteur non technique
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

Le classeur `output/Credit_Risk_IRB_IFRS9_sortie.xlsx` est généré avec les onglets : données obligors, synthèse par grade (population x grade), synthèse par population, décomposition MoC, synthèse staging IFRS 9, synthèse par périmètre, série annuelle de défaut (LRA), panel brut d'observations LRA, résultats des tests de stress par scénario, résultat du stress test inverse, validation AUC/Gini Train/OOT, VIF des variables de segmentation, validation ANOVA (homogénéité intra/inter-classe), arbre de Belson (traçabilité des règles de segmentation).

## Conventions du projet

- Le détail méthodologique complet (formules, articles réglementaires, limites assumées) est dans `docs/METHODOLOGY.md` (version avec formules) et `docs/METHODOLOGY_SANS_FORMULES.md` (version pédagogique, sans formule).
- La segmentation du risque se fait en deux temps : `populationSegmentation.py` (étape 5, DBSCAN + KMeans sur la capacité économique : revenu, qualification, ratios d'endettement) puis `riskClustering.py` (étape 6, algorithme de Belson + validation ANOVA, appliqué séparément à l'intérieur de chaque population). Deux obligors de capacité économique très différente ne sont jamais notés par le même modèle de PD (Art. 170 CRR).

## Warnings

Les dates, le périmètre PME/Corporate, les revenus et les flux de recouvrement sont **simulés** : le jeu de données source ne contient aucune de ces informations. Voir `docs/METHODOLOGY.md` (section 0 et section 12) pour le détail des hypothèses et des limites assumées, notamment le pouvoir discriminant du modèle (AUC/Gini, section 11).
