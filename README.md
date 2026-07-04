# Projet Risque de Crédit — IRB-A / IFRS 9 / CRR2-CRR3

**Auteur :** Rodrigue KOFFI

Pipeline Python modulaire de notation interne (IRB-A) et de provisionnement IFRS 9, construit à partir du jeu de données German Credit Data, retraité pour simuler un cycle de vie de crédit réaliste (chronologie, périmètre Retail/PME, coûts de recouvrement, tests de stress).

Ce projet fait suite à un entretien technique risque de crédit : il corrige les points explicitement soulevés (absence de PD Long Run Average, MoC A/B/C non conformes à l'EBA GL/2017/16, fenêtre de performance à l'octroi trop restrictive) et refond le script initial monolithique en pipeline modulaire, chronologique et documenté.

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

## Conventions du projet

- **Nommage** : camelCase explicite partout (`riskGradeClass`, `pdFinalRegulatory`...), aucune notation générique type `x_train`/`y_t`.
- **Pas de `logging` Python** : traçabilité d'exécution via des impressions structurées (`print`), module par module.
- **Aucune simplification volontaire** : formule de Bâle complète (corrélation, ajustement de maturité), LGD par méthode workout, PD calibrée en Long Run Average + MoC A/B/C sur un panel d'observations multi-années, stress test inverse résolu numériquement, validation statistique (Train/OOT, AUC, Gini, VIF).
- Le détail méthodologique complet (formules, articles réglementaires, limites assumées) est dans `docs/METHODOLOGY.md`.

## Avertissement

Les dates, le périmètre PME/Corporate, les revenus et les flux de recouvrement sont **simulés** : le jeu de données source ne contient aucune de ces informations. Voir `docs/METHODOLOGY.md` (section 0 et section 12) pour le détail des hypothèses et des limites assumées, notamment le pouvoir discriminant du modèle (AUC/Gini, section 11).
