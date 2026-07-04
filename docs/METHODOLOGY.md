# Méthodologie du projet — Modèle IRB-A / IFRS 9 (Crédit Retail & PME)

**Auteur :** Rodrigue KOFFI
**Périmètre :** Portefeuille de crédit à la consommation (German Credit Data), enrichi et retraité pour simuler un portefeuille bancaire réaliste (Retail / PME / Corporate-SME).

---

## 0. Pourquoi ce document existe

Ce mémo répond directement aux remarques formulées lors de l'entretien technique :

1. **La PD n'utilisait pas de Long Run Average (LRA).**
2. **La Marge de Conservatisme (MoC) n'était pas construite selon les catégories A / B / C.**

Il documente, module par module, les formules utilisées, leur justification économique, et les articles réglementaires correspondants (CRR — Règlement UE 575/2013 tel que modifié par CRR2/CRR3, CRD IV/V, EBA Guidelines, IFRS 9).

**Avertissement de portée** : le jeu de données source (German Credit Data, 1000 dossiers, 10 variables) ne contient ni date, ni segment PME, ni flux de recouvrement. Toutes les données temporelles, le périmètre PME/Corporate, les revenus, les flux de recouvrement et les coûts de gestion du contentieux sont **simulés** pour permettre un pipeline méthodologiquement complet. Chaque donnée simulée est signalée dans le code (`src/*.py`) et ci-dessous.

---

## Glossaire des termes clés

Cette section précède les sections méthodologiques et fixe une définition unique de chaque terme, pour éviter toute ambiguïté entre les modules (en particulier la notion de **défaut**, qui doit être lue de la même façon partout dans ce document et dans le code).

**Obligor** — Personne physique ou morale ayant une obligation de remboursement envers la banque (l'emprunteur). Le défaut est défini au niveau de l'obligor (Art. 178 CRR), pas du contrat : un obligor a un statut de défaut unique, même s'il détient plusieurs facilités.

**Défaut (Default)** — Au sens réglementaire (Art. 178 CRR), un obligor est en défaut si (a) la banque juge improbable qu'il rembourse intégralement ses obligations sans réalisation de la garantie (*Unlikeliness to Pay*), et/ou (b) il est en arriéré de plus de 90 jours consécutifs sur une obligation de crédit significative (*backstop* jours de retard).

*Application dans ce projet* : la base source ne fournit qu'un label binaire atemporel (`good`/`bad`), sans date ni motif. `defaultEverFlag` sert de vérité terrain simplifiée ("cet obligor connaîtra un défaut à un moment de sa vie"). `Tcg.py` lui assigne une **date de défaut unique** (`defaultDate`) dans la durée de vie du crédit. Le défaut est un événement **absorbant** : une fois survenu, l'obligor reste en défaut (pas de retour "in bonis" modélisé). C'est cette date unique qui est ensuite testée contre **plusieurs fenêtres d'observation annuelles successives** (le panel décrit en section 2.A) — et non contre une seule fenêtre à l'octroi — pour déterminer, à chaque point de vie du crédit, si le défaut survient dans les 12 mois qui suivent. C'est ce mécanisme, corrigé en section 2.A, qui doit rester la seule référence : toute description antérieure d'une fenêtre unique à l'octroi est obsolète.

**Fenêtre de performance à 12 mois** — Intervalle `(t, t+12 mois]` à partir d'un point d'observation `t` (pas nécessairement l'octroi), utilisé pour mesurer si un défaut survient dans l'horizon réglementaire d'un an (Art. 178 CRR, EBA GL/2016/07).

**Anniversaire vs cycle calendaire — approche retenue (à ne pas confondre)** : le projet combine délibérément les deux logiques, à deux étapes différentes :
- *Génération des points d'observation* : ancrée sur la **date anniversaire du contrat** (`originationDate`, puis +12 mois, +24 mois, ...), propre à chaque dossier — pas sur un calendrier civil fixe (1er janvier). Chaque fenêtre testée est ainsi toujours complète et non tronquée arbitrairement.
- *Agrégation de la série pour la LRA* : chaque observation est étiquetée par l'**année calendaire** dans laquelle tombe son anniversaire (`performanceYear = t.year`), et non par l'âge du crédit (1ère, 2e, 3e année de vie...). C'est ce qui permet de faire ressortir correctement les années de choc macroéconomique (2012, 2020) dans le calcul de la LRA (section 4), quel que soit l'âge des crédits qui y contribuent cette année-là.

**PD (Probability of Default)** — Probabilité qu'un obligor fasse défaut dans les 12 mois. On distingue la **PD TTC** (Through-The-Cycle, LRA + MoC, utilisée pour le capital IRB) de la **PD PIT** (Point-In-Time, ajustée des conditions actuelles, utilisée pour l'IFRS 9).

**LRA (Long Run Average)** — Moyenne des taux de défaut annuels observés sur un historique représentatif d'un cycle économique complet (section 4), construite ici à partir du panel d'observations et non d'un flag unique par dossier.

**MoC (Margin of Conservatism)** — Marge additive appliquée à la PD LRA pour couvrir l'incertitude résiduelle, décomposée en catégories A (erreur d'estimation générale), B (déficiences de données/méthode identifiées) et C (changements de contexte non encore reflétés) — détail en section 5.

**LGD (Loss Given Default)** — Proportion de l'exposition effectivement perdue en cas de défaut, après recouvrement et déduction des coûts (section 6).

**EAD (Exposure At Default)** — Montant de l'exposition au moment du défaut (section 7).

**Grade / Pool de risque** — Classe homogène de risque (`veryLow` à `veryHigh`) à laquelle un obligor est affecté par clustering (section 3), et à laquelle une PD LRA + MoC est associée.

**SICR (Significant Increase in Credit Risk)** — Dégradation significative du risque de crédit depuis l'octroi, déclenchant le passage en Stage 2 sous IFRS 9 (section 8).

**Stage IFRS 9** — Classification en 3 niveaux (Stage 1 : sain, Stage 2 : SICR avéré, Stage 3 : en défaut) déterminant l'horizon de calcul de l'ECL.

**ECL (Expected Credit Loss)** — Perte de crédit attendue, calculée comme PD × LGD × EAD, actualisée, sur un horizon de 12 mois (Stage 1) ou à maturité (Stage 2/3).

**RWA (Risk Weighted Assets)** — Actifs pondérés du risque, base de calcul du capital réglementaire IRB (section 9).

**Périmètre (Retail / Retail-SME / Corporate-SME)** — Segmentation réglementaire du portefeuille définissant le champ d'application du modèle (section 1).

**Train / Out-Of-Time (OOT)** — Découpage chronologique du panel d'observations en deux sous-périodes pour tester la stabilité dans le temps du pouvoir discriminant : Train = années antérieures à un seuil fixé (ici 2022), OOT = années postérieures ou égales à ce seuil, non utilisées de la même façon lors de la calibration (section 11).

**AUC (Area Under the ROC Curve)** — Mesure du pouvoir discriminant d'un score ou d'un classement (ici le rang du grade) face à un événement binaire (défaut) : 0,50 = aucun pouvoir discriminant (équivalent au hasard), 1,00 = discrimination parfaite (section 11).

**Gini** — Transformation linéaire de l'AUC (Gini = 2 × AUC − 1), échelle usuelle en risque de crédit : 0 = aucun pouvoir discriminant, proche de 1 = discrimination très forte (section 11).

**VIF (Variance Inflation Factor)** — Mesure de la colinéarité d'une variable explicative avec les autres variables d'un même modèle (VIF = 1 / (1 − R²) de sa régression contre les autres) ; un VIF > 5 signale une redondance à traiter (section 11).

---

## 1. Périmètre (`perimeterDefinition.py`) — CRR Art. 142, 147, 123

Chaque obligor est classé :
- `RETAIL_CONSUMER` : particulier, crédit à la consommation classique.
- `RETAIL_SME` : petite activité indépendante, exposition < seuil Art. 123 CRR (1 M EUR) → reste en portefeuille Retail.
- `CORPORATE_SME` : sous-population simulée pour illustrer l'ajustement de corrélation "taille de firme" (Art. 153(4)).

> **Limite assumée** : les montants du dataset restant tous < 1 M EUR, une PME y resterait en toute rigueur dans le portefeuille Retail (Art. 123). Le segment `CORPORATE_SME` est un choix pédagogique explicite.

Revenu mensuel et données PME (chiffre d'affaires, effectifs) sont simulés car absents de la base source mais indispensables au calcul des ratios d'endettement et à l'ajustement de corrélation PME.

---

## 2. Chronologie et panel d'observations (`Tcg.py`) — CRR Art. 178

Deux notions de temps distinctes :

### A. Panel d'observations annuelles (calibration LRA)

**Point corrigé suite à relecture technique.** Une fenêtre unique à l'octroi (t0 → t0+12 mois) ne capture que les défauts précoces. Un crédit octroyé en 2011 qui fait défaut en 2014 ne serait alors JAMAIS compté comme un défaut — il "survivrait" artificiellement la seule fenêtre mesurée, ce qui sous-estime la PD réelle du portefeuille.

La bonne pratique EBA GL/2017/16 observe chaque dossier à **plusieurs reprises au cours de sa vie** (anniversaires successifs), et teste à chaque point s'il fait défaut dans les 12 mois qui suivent CE point précis :

```
pour chaque dossier, tant qu'il est vivant et que la fenêtre est entièrement réalisée :
    t = originationDate, originationDate+12m, originationDate+24m, ...
    default12mFlag(t) = 1  si  t < defaultDate <= t + 12 mois   -> le dossier sort de la population, arrêt
    default12mFlag(t) = 0  si  aucun défaut dans (t, t+12 mois] ET le crédit est encore actif à t+12 mois
    (observation exclue si la fenêtre n'est pas encore entièrement réalisée à la date d'arrêté,
     ou si le crédit arrive à échéance avant la fin des 12 mois -> fenêtre censurée)
```

**Exemple concret** : origination en 2011, défaut en 2014.
- Observation 2011 (fenêtre 2011→2012) : pas de défaut → `default12mFlag = 0`
- Observation 2012 (fenêtre 2012→2013) : pas de défaut → `default12mFlag = 0`
- Observation 2013 (fenêtre 2013→2014) : défaut constaté → `default12mFlag = 1`, le dossier sort de la population

Ce dossier contribue ainsi correctement à la série de taux de défaut annuels, à la bonne année (2013), plutôt que de disparaître silencieusement. Implémenté dans `buildAnnualPerformancePanel()`, qui produit un **panel** (plusieurs lignes par dossier) et non plus un flag unique par dossier. Sur le portefeuille simulé : environ 1 100 observations annuelles sur ~770 dossiers actifs au moins une fois dans l'historique (2010–2023).

Un indicateur diagnostique `firstYearDefaultFlag` (défaut dans la 1ère année uniquement) est conservé à titre de comparaison dans les exports, mais **n'alimente plus la calibration LRA**.

### B. Statut du livre à la date d'arrêté (staging IFRS 9)
À la date de reporting (`OBSERVATION_DATE`), chaque dossier est classé `ACTIVE`, `DEFAULTED` ou `MATURED`. Seuls `ACTIVE` et `DEFAULTED` entrent dans le calcul de l'ECL. Un proxy d'arriérés (`daysPastDue`) est simulé pour le backstop des 30 jours de l'IFRS 9.

---

## 3. Clustering du risque (`riskClustering.py`) — CRR Art. 170

1. **DBSCAN** sur les variables standardisées → détection des dossiers atypiques (bruit, label `-1`), isolés en segment `outlierReview`.
2. **KMeans (k=5)** sur la population cœur → 5 pools de risque homogènes.
3. Les clusters bruts n'ont pas d'ordre intrinsèque : ils sont classés par **taux de défaut observé (`defaultEverFlag`) croissant**, puis mappés vers `veryLow → veryHigh`. Ce classement sert uniquement à ORDONNER les grades ; la PD effectivement utilisée provient de la calibration LRA (section 4), pas de ce taux brut.

---

## 4. PD Long Run Average — EBA GL/2017/16 (§88-94), CRR Art. 180

**Point n°1 de l'entretien.** La LRA n'est pas le taux de défaut du dernier échantillon disponible, mais la **moyenne des taux de défaut annuels** :

```
PD_LRA(grade) = moyenne_années( tauxDéfautAnnuel(grade, année) )   pour année ∈ [2010, 2023]
```

où `tauxDéfautAnnuel(grade, année)` provient du **panel d'observations annuelles** (section 2.A) — chaque dossier pouvant contribuer à plusieurs années de performance — et non d'un flag unique par dossier à l'octroi. La série couvre jusqu'à 14 années calendaires, incluant deux années de choc (2012, 2020). Une correction de monotonie (Pool Adjacent Violators) garantit `PD_LRA(veryLow) ≤ ... ≤ PD_LRA(veryHigh)`.

> Constat de validation (transparence) : sur ce jeu de données, les grades `medium`, `high` et `veryHigh` convergent après correction de monotonie vers une PD quasi identique — signe d'une différenciation insuffisante entre ces trois grades (cohérent avec le silhouette score modéré du clustering, section 11). En production, cela déclencherait une revue du pouvoir discriminant du modèle avant validation.

---

## 5. Marge de Conservatisme (MoC A / B / C) — EBA GL/2017/16 (§41-52), CRR Art. 179(1)(f)

**Point n°2 de l'entretien.** La MoC est un **add-on additif** appliqué à la LRA :

```
PD_finale = PD_LRA + MoC_A + MoC_B + MoC_C
```

| Catégorie | Nature | Implémentation |
|---|---|---|
| **MoC A** | Erreur d'estimation générale (incertitude statistique liée à la taille de l'échantillon) | Intervalle de confiance de Wilson à 95 % sur le taux de défaut agrégé du grade ; MoC_A = borne supérieure − PD_LRA |
| **MoC B** | Déficiences de données/méthode identifiées (dates simulées, revenu proxy, notation par clustering non supervisé) | Add-on forfaitaire documenté (15 bps), à valider en comité des modèles |
| **MoC C** | Changements pertinents non encore reflétés dans la LRA (dérive du mix de risque, politique d'octroi) | Population Stability Index (PSI) entre la distribution des grades du millésime le plus récent et l'historique ; add-on proportionnel si PSI > 0,10 |

---

## 6. LGD — méthode workout (`lgdEstimation.py`) — CRR Art. 181, EBA GL/2019/03

```
LGD_réalisée = 1 − [ VA(recouvrements) − coûts_directs − coûts_indirects ] / EAD_au_défaut
```

Les flux de recouvrement, leur délai et les coûts de gestion du contentieux sont simulés (fonction du collatéral proxy, du segment, avec bruit) puis actualisés au taux `RECOVERY_DISCOUNT_RATE_ANNUAL`. La **LGD downturn** (Art. 181(1)(b)) retient, par cellule grade × segment, le plus conservateur entre la LGD moyenne tout-cycle et la LGD moyenne des seules années de choc.

---

## 7. EAD et CCF (`eadEstimation.py`) — CRR Art. 166

EAD = encours amorti à la date d'arrêté + `CCF × ligne hors bilan` pour le segment PME/Corporate. Les CCF appliqués sont indicatifs et à rapprocher, en production, des valeurs supervisées (F-IRB) ou des CCF internes validés (A-IRB).

---

## 8. Staging IFRS 9 et ECL (`ifrs9Staging.py`) — IFRS 9 §5.5, EBA GL/2016/07

La PD Through-The-Cycle (LRA + MoC) sert au **capital réglementaire** (IRB). L'IFRS 9 exige une PD **Point-In-Time** (PIT), recalculée à chaque date de reporting :

```
PD_PIT = PD_origination × multiplicateur_macro × multiplicateur_arriérés × multiplicateur_backstop
```

Le SICR (§5.5.9) est détecté par un faisceau de 3 indices : augmentation relative de la PD ≥ ×2 depuis l'octroi, augmentation absolue ≥ 75 bps, backstop de 30 jours d'arriérés (§5.5.11).

| Stage | Condition | ECL |
|---|---|---|
| 1 | Sain, pas de SICR | PD 12 mois × LGD × EAD (actualisé) |
| 2 | SICR avéré | PD lifetime × LGD × EAD (actualisé) |
| 3 | Défaut constaté à l'arrêté | PD lifetime × LGD × EAD (actualisé) |

---

## 9. Capital réglementaire IRB-A (`irbCapitalRwa.py`) — CRR Art. 153, 154, 162, 501

Formule de Bâle complète (et non `RWA ≈ 12,5×PD×LGD` simplifié) :

```
K = LGD × [ N( √(1/(1−R)) × G(PD) + √(R/(1−R)) × G(0,999) ) − PD ] × MA
RWA = K × 12,5 × EAD
```

- **Corrélation R** : Retail (Art. 154) via fonction exponentielle de la PD ; Corporate/PME-Corporate (Art. 153) avec ajustement taille de firme pour CA ∈ [5, 50] M EUR (Art. 153(4)).
- **Ajustement de maturité MA** (Corporate/PME-Corporate uniquement, Art. 162), non appliqué au Retail.
- **Facteur supportant PME** (Art. 501) : abattement de RWA (×0,7619) pour les expositions PME ≤ 50 M EUR de CA.

Le capital total intègre le Pilier 1 (8 %), le coussin de conservation (2,5 %) et le coussin contracyclique (1 %).

---

## 10. Tests de stress et stress test inverse (`stressTesting.py`) — CRR Art. 177, EBA GL/2018/04

Exigence explicite de l'Art. 177 CRR : un système IRB doit intégrer des tests de résistance solides.

### A. Tests de stress par scénario
Trois scénarios pondérés appliquent un choc relatif au taux de chômage utilisé dans la composante macro de la PD PIT :

| Scénario | Choc chômage | Poids |
|---|---|---|
| Baseline | 0 % | 50 % |
| Upside | −20 % | 25 % |
| Downside | +35 % | 25 % |

Pour chaque scénario, l'ECL du livre noté (Stage 1/2/3) est recalculée avec une PD PIT et une PD lifetime choquées, puis pondérée par la probabilité du scénario.

### B. Stress test inverse (reverse stress test)
On part d'une perte limite — le capital total requis (Pilier 1 + coussins) — et on cherche, par résolution numérique (bissection, `scipy.optimize.brentq`), le choc de chômage relatif au-delà duquel l'ECL du portefeuille dépasse ce capital disponible : *quel choc casse le coussin de capital de la banque ?* Sur le portefeuille simulé, le point de rupture est trouvé autour de +60 % de choc chômage relatif. C'est une amélioration par rapport à une inversion algébrique d'une formule simplifiée : ici le stress test inverse est cohérent avec la vraie ECL IFRS 9 et le vrai capital IRB calculés en amont.

---

## 11. Validation statistique : Train/OOT, AUC, Gini, VIF (`modelValidation.py`) — EBA GL/2017/16 (validation)

EBA/GL/2017/16 demande de valider le pouvoir discriminant du système de notation (rank ordering des classes de risque face au défaut réellement observé) et sa stabilité dans le temps. Le classement de risque provenant ici d'un clustering non supervisé (DBSCAN + KMeans) et non d'une régression logistique, le « score » utilisé pour l'AUC/Gini est le rang ordinal du grade (`veryLow`=0 … `veryHigh`=4, `outlierReview`=5).

### A. Découpage Train / Out-Of-Time (OOT)
Le panel d'observations annuelles (`performancePanel`) est scindé par année de performance : Train = années < `OOT_START_YEAR` (2022), OOT = années ≥ 2022. Objectif : vérifier que le pouvoir discriminant du grade reste stable sur une période non utilisée pour l'essentiel de l'historique de calibration, plutôt que de le mesurer uniquement en cumulé.

**Limite assumée et documentée** : le classement des clusters par grade (`riskClustering.py`) utilise `defaultEverFlag`, calculé sur l'historique complet (Train + OOT). Ce découpage Train/OOT mesure donc la **stabilité** du pouvoir discriminant dans le temps, pas une validation hors échantillon au sens strict d'un modèle réestimé uniquement sur le Train. Un raffinement futur consisterait à reclasser les clusters en n'utilisant que les défauts antérieurs à 2022.

### B. AUC et Gini (pouvoir discriminant)
Gini = 2 × AUC − 1. Résultats obtenus sur le portefeuille simulé :

| Échantillon | Observations | Taux de défaut | AUC | Gini |
|---|---|---|---|---|
| Ensemble du panel | 1 143 | 23,5 % | 0,519 | 0,038 |
| Train (< 2022) | 939 | 23,6 % | 0,516 | 0,032 |
| Out-Of-Time (≥ 2022) | 204 | 23,0 % | 0,538 | 0,075 |

**Lecture honnête** : un AUC proche de 0,50 (Gini proche de 0) indique un pouvoir discriminant faible — le grade sépare à peine mieux le défaut que le hasard. C'est cohérent avec le silhouette score modéré du clustering (section 3) : les variables sociodémographiques du dataset source (âge, épargne, logement) sont structurellement peu prédictives du défaut à 12 mois. Le Gini est légèrement meilleur sur l'OOT que sur le Train ici, mais l'échantillon OOT est petit (204 observations) : cet écart n'est pas interprété comme une amélioration du modèle, seulement rapporté pour transparence.

### C. VIF (colinéarité des variables de segmentation)
Le VIF (Variance Inflation Factor) de chaque variable numérique utilisée par le clustering est calculé par régression linéaire de la variable contre les autres (VIF = 1 / (1 − R²)), seuil d'alerte usuel = 5 :

| Variable | VIF |
|---|---|
| `creditToAnnualIncomeRatio` | 6,61 ⚠ |
| `creditAmountScaledLog` | 4,11 |
| `installmentToIncomeRatio` | 3,06 |
| `durationMonths` | 2,49 |
| `jobSkillLevel` | 1,50 |
| `age`, `housingCollateralProxyScore`, `savingAccountScore`, `checkingAccountScore` | ~1,0 |

`creditToAnnualIncomeRatio` dépasse le seuil de 5 : elle est mécaniquement corrélée à `creditAmountScaledLog`, `installmentToIncomeRatio` et `durationMonths` (toutes dérivées du même montant de crédit). Piste d'amélioration : ne conserver qu'une des variables dérivées du montant de crédit, ou passer à une réduction de dimension (ACP) avant clustering.

---

## 12. Limites connues et pistes d'amélioration (transparence de validation)

- Le pouvoir discriminant du grade est faible (AUC ≈ 0,52, Gini ≈ 0,04 — cf. section 11) : à documenter explicitement dans tout usage réel de ce projet, ce n'est pas un modèle prêt pour la production.
- Le silhouette score du clustering (~0,18-0,25) indique une séparation modérée des classes de risque : en production, il faudrait enrichir les variables de risque (score bureau, historique de paiement) plutôt que les seules variables du dataset source.
- Les grades `medium`/`high`/`veryHigh` convergent partiellement après correction de monotonie (cf. section 4) : signal de pouvoir discriminant à améliorer.
- Une variable (`creditToAnnualIncomeRatio`) présente un VIF > 5 (cf. section 11.C) : redondance avec d'autres variables dérivées du montant de crédit.
- Les données temporelles, PME, de recouvrement et de coûts sont simulées : ce projet est une démonstration méthodologique de bout en bout, pas un modèle validé sur données réelles.
- Le segment `CORPORATE_SME` est une construction pédagogique (cf. section 1) à ne pas reproduire telle quelle en production sans revalider le seuil Art. 123.

---

---

## Références réglementaires citées — lecture officielle

Cette section donne, pour chaque texte cité dans le document, la référence officielle complète (numéro, date, intitulé exact) telle que publiée au Journal Officiel de l'UE ou par l'EBA/IASB — pas une paraphrase.

### Corpus prudentiel bancaire (CRR/CRD)

| Texte | Référence officielle | Date | Nature |
|---|---|---|---|
| **CRR** (socle) | Règlement (UE) n° 575/2013 du Parlement européen et du Conseil du 26 juin 2013 | 26/06/2013 | Règlement — directement applicable, sans transposition nationale |
| **CRD IV** (socle) | Directive 2013/36/UE du Parlement européen et du Conseil du 26 juin 2013 | 26/06/2013 | Directive — transposition nationale requise (gouvernance, coussins, rémunérations) |
| **CRR II** | Règlement (UE) 2019/876 du 20 mai 2019 modifiant le règlement (UE) n° 575/2013 | 20/05/2019, application 28/06/2021 | Ratio de levier, NSFR, TLAC, risque de contrepartie |
| **CRD V** | Directive (UE) 2019/878 du 20 mai 2019 modifiant la directive 2013/36/UE | 20/05/2019 | Gouvernance, holdings intermédiaires, Pilier 2 |
| **CRR III** | Règlement (UE) 2024/1623 du 31 mai 2024 modifiant le règlement (UE) n° 575/2013 | Entrée en vigueur 09/07/2024, application 01/01/2025 | Finalisation Bâle III : output floor, révision des approches standards et IRB |
| **CRD VI** | Directive (UE) 2024/1619 du 31 mai 2024 modifiant la directive 2013/36/UE | Transposition avant le 10/01/2026 | Succursales pays tiers, risques ESG, gouvernance |

Articles CRR cités dans ce document : 123, 142, 147, 153, 154, 162, 166, 170, 174, 177, 178, 179, 180, 181, 501.

### Guidelines EBA (niveau 3 — précisent l'application du CRR)

- **EBA/GL/2017/16** — *Guidelines on PD estimation, LGD estimation and the treatment of defaulted exposures*, publiées novembre 2017, application au 1er janvier 2021. Base de la calibration LRA et de la MoC A/B/C (sections 4 et 5).
- **EBA/GL/2019/03** — *Guidelines for the estimation of LGD appropriate for an economic downturn ('Downturn LGD estimation')*, publiées le 6 mars 2019, application au 1er janvier 2021. Base de la LGD downturn (section 6).
- **EBA/GL/2016/07** — *Guidelines on the application of the definition of default under Article 178 of Regulation (EU) No 575/2013*, publiées le 28 septembre 2016, application au 1er janvier 2021. Base de la définition du défaut (Glossaire, section 2).
- **EBA/GL/2018/04** — *Guidelines on institutions' stress testing*, application au 1er janvier 2019, dans le cadre de l'ICAAP (Art. 73 CRD IV). Base des tests de stress et du stress test inverse (section 10).

### Norme comptable

- **IFRS 9** — *Financial Instruments*, publiée par l'IASB le 24 juillet 2014, effective de manière obligatoire depuis le 1er janvier 2018, adoptée dans l'UE par le règlement (UE) 2016/2067. §5.5 (dépréciation/ECL) est la base des sections 8 et 10.
