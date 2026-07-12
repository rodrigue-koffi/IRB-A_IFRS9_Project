# Méthodologie du projet — Modèle IRB-A / IFRS 9 (Crédit Retail & PME)

**Auteur :** Rodrigue KOFFI
**Périmètre :** Portefeuille de crédit à la consommation (German Credit Data), enrichi et retraité pour simuler un portefeuille bancaire réaliste (Retail / PME / Corporate-SME).

---

## 0. Pourquoi ce document existe

Ce mémo documente les points méthodologiques centraux du pipeline, en particulier :

1. **La PD utilise un Long Run Average (LRA)**, désormais calibré au niveau de la cellule (populationSegment × riskGradeClass) et stabilisé par une pondération de crédibilité actuarielle avant tout contrôle de monotonie (section 5).
2. **La segmentation du risque se construit en deux temps distincts** : une segmentation de POPULATION non supervisée par capacité économique (DBSCAN + KMeans, section 3), puis une segmentation de RISQUE supervisée par le défaut à l'intérieur de chaque population (algorithme de Belson, section 4), validée par une analyse de variance (ANOVA).
3. **La Marge de Conservatisme (MoC)** est construite selon les catégories A / B / C, appliquées elles aussi au niveau de la cellule (section 6).

Il documente, module par module, les formules utilisées, leur justification économique, et les articles réglementaires correspondants (CRR — Règlement UE 575/2013 tel que modifié par CRR2/CRR3, CRD IV/V, EBA Guidelines, IFRS 9), ainsi que les techniques statistiques/actuarielles classiques mobilisées (algorithme de Belson, théorie de la crédibilité de Bühlmann) qui ne sont pas d'origine réglementaire mais relèvent de bonnes pratiques de modélisation statistique.

 le jeu de données source (German Credit Data, 1000 dossiers, 10 variables) ne contient ni date, ni segment PME, ni flux de recouvrement, ni revenu. Toutes les données temporelles, le périmètre PME/Corporate, les revenus, les flux de recouvrement et les coûts de gestion du contentieux sont **simulés** pour permettre un pipeline méthodologiquement complet. Chaque donnée simulée est signalée dans le code (`src/*.py`) et ci-dessous.

---

## Glossaire des termes clés

Cette section précède les sections méthodologiques et fixe une définition unique de chaque terme, pour éviter toute ambiguïté entre les modules (en particulier la notion de **défaut**, qui doit être lue de la même façon partout dans ce document et dans le code).

**Obligor** — Personne physique ou morale ayant une obligation de remboursement envers la banque (l'emprunteur). Le défaut est défini au niveau de l'obligor (Art. 178 CRR), pas du contrat : un obligor a un statut de défaut unique, même s'il détient plusieurs facilités.

**Défaut (Default)** — Au sens réglementaire (Art. 178 CRR), un obligor est en défaut si (a) la banque juge improbable qu'il rembourse intégralement ses obligations sans réalisation de la garantie (*Unlikeliness to Pay*), et/ou (b) il est en arriéré de plus de 90 jours consécutifs sur une obligation de crédit significative (*backstop* jours de retard).

*Application dans ce projet* : la base source ne fournit qu'un label binaire atemporel (`good`/`bad`), sans date ni motif. `defaultEverFlag` sert de vérité terrain simplifiée ("cet obligor connaîtra un défaut à un moment de sa vie"). `Tcg.py` lui assigne une **date de défaut unique** (`defaultDate`) dans la durée de vie du crédit. Le défaut est un événement **absorbant** : une fois survenu, l'obligor reste en défaut (pas de retour "in bonis" modélisé). C'est cette date unique qui est ensuite testée contre **plusieurs fenêtres d'observation annuelles successives** (le panel décrit en section 2.A) — et non contre une seule fenêtre à l'octroi — pour déterminer, à chaque point de vie du crédit, si le défaut survient dans les 12 mois qui suivent.

**Population (populationSegment)** — Groupe homogène de capacité économique (revenu, qualification, ratios d'endettement) auquel un obligor est affecté par clustering non supervisé (section 3), **avant** toute notation de risque. `populationModeste`, `populationIntermediaire`, `populationAisee`, ou `populationOutlierReview` pour les profils atypiques isolés.

**Fenêtre de performance à 12 mois** — Intervalle `(t, t+12 mois]` à partir d'un point d'observation `t` (pas nécessairement l'octroi), utilisé pour mesurer si un défaut survient dans l'horizon réglementaire d'un an (Art. 178 CRR, EBA GL/2016/07).

**Anniversaire vs cycle calendaire — approche retenue (à ne pas confondre)** : le projet combine délibérément les deux logiques, à deux étapes différentes :
- *Génération des points d'observation* : ancrée sur la **date anniversaire du contrat** (`originationDate`, puis +12 mois, +24 mois, ...), propre à chaque dossier — pas sur un calendrier civil fixe (1er janvier).
- *Agrégation de la série pour la LRA* : chaque observation est étiquetée par l'**année calendaire** dans laquelle tombe son anniversaire (`performanceYear = t.year`), et non par l'âge du crédit. C'est ce qui permet de faire ressortir correctement les années de choc macroéconomique (2012, 2020) dans le calcul de la LRA (section 5), quel que soit l'âge des crédits qui y contribuent cette année-là.

**PD (Probability of Default)** — Probabilité qu'un obligor fasse défaut dans les 12 mois. On distingue la **PD TTC** (Through-The-Cycle, LRA + MoC, utilisée pour le capital IRB) de la **PD PIT** (Point-In-Time, ajustée des conditions actuelles, utilisée pour l'IFRS 9).

**LRA (Long Run Average)** — Moyenne des taux de défaut annuels observés sur un historique représentatif d'un cycle économique complet (section 5), construite à partir du panel d'observations et non d'un flag unique par dossier, calibrée au niveau de la cellule (populationSegment × riskGradeClass), et stabilisée par une pondération de crédibilité actuarielle avant tout contrôle de monotonie.

**Crédibilité actuarielle (credibility, Bühlmann)** — Technique statistique classique (assurance/actuariat) consistant à pondérer une estimation propre à un segment fin par un facteur croissant avec la taille de son échantillon, le complément étant apporté par une estimation plus large et donc plus stable (le "prior"). Utilisée ici pour stabiliser la LRA de cellules (population × grade) à faible effectif (section 5).

**MoC (Margin of Conservatism)** — Marge additive appliquée à la PD LRA de chaque cellule pour couvrir l'incertitude résiduelle, décomposée en catégories A (erreur d'estimation générale), B (déficiences de données/méthode identifiées) et C (changements de contexte non encore reflétés) — détail en section 6.

**Algorithme de Belson** — Méthode de segmentation binaire récursive supervisée (D.J. Belson, 1959), précurseur des méthodes AID/CHAID : à chaque nœud, elle sélectionne la variable et le seuil qui maximisent l'association statistique (test du Chi²) avec une variable cible binaire. Utilisée ici (section 4) pour construire les classes de risque à l'intérieur de chaque population, en utilisant `defaultEverFlag` comme cible.

**LGD (Loss Given Default)** — Proportion de l'exposition effectivement perdue en cas de défaut, après recouvrement et déduction des coûts (section 7).

**EAD (Exposure At Default)** — Montant de l'exposition au moment du défaut (section 8).

**Grade / Pool de risque (riskGradeClass)** — Classe homogène de risque (`veryLow` à `veryHigh`) à laquelle un obligor est affecté par l'algorithme de Belson, **à l'intérieur de sa population** (section 4). Le même libellé de grade peut porter des PD différentes selon la population (section 5).

**SICR (Significant Increase in Credit Risk)** — Dégradation significative du risque de crédit depuis l'octroi, déclenchant le passage en Stage 2 sous IFRS 9 (section 9).

**Stage IFRS 9** — Classification en 3 niveaux (Stage 1 : sain, Stage 2 : SICR avéré, Stage 3 : en défaut) déterminant l'horizon de calcul de l'ECL.

**ECL (Expected Credit Loss)** — Perte de crédit attendue, calculée comme PD × LGD × EAD, actualisée, sur un horizon de 12 mois (Stage 1) ou à maturité (Stage 2/3).

**RWA (Risk Weighted Assets)** — Actifs pondérés du risque, base de calcul du capital réglementaire IRB (section 10).

**Périmètre (Retail / Retail-SME / Corporate-SME)** — Segmentation réglementaire du portefeuille définissant le champ d'application du modèle (section 1). À ne pas confondre avec `populationSegment` (section 3), qui est une segmentation par capacité économique, orthogonale au périmètre réglementaire.

**Train / Out-Of-Time (OOT)** — Découpage chronologique du panel d'observations en deux sous-périodes pour tester la stabilité dans le temps du pouvoir discriminant : Train = années antérieures à un seuil fixé (ici 2022), OOT = années postérieures ou égales à ce seuil (section 12).

**AUC (Area Under the ROC Curve)** — Mesure du pouvoir discriminant d'un score ou d'un classement face à un événement binaire (défaut) : 0,50 = aucun pouvoir discriminant, 1,00 = discrimination parfaite (section 12).

**Gini** — Transformation linéaire de l'AUC (Gini = 2 × AUC − 1), échelle usuelle en risque de crédit (section 12).

**VIF (Variance Inflation Factor)** — Mesure de la colinéarité d'une variable explicative avec les autres variables d'un même modèle (VIF = 1 / (1 − R²) de sa régression contre les autres) ; un VIF > 5 signale une redondance à traiter (section 12).

**ANOVA (analyse de variance à un facteur)** — Test statistique comparant la variance "between" (entre groupes) à la variance "within" (au sein des groupes) via la statistique F, utilisé ici pour vérifier l'homogénéité intra-classe / hétérogénéité inter-classe exigée par l'Art. 170 CRR (section 4).

---

## 1. Périmètre (`perimeterDefinition.py`) — CRR Art. 142, 147, 123

Chaque obligor est classé :
- `RETAIL_CONSUMER` : particulier, crédit à la consommation classique.
- `RETAIL_SME` : petite activité indépendante, exposition < seuil Art. 123 CRR (1 M EUR) → reste en portefeuille Retail.
- `CORPORATE_SME` : sous-population simulée pour illustrer l'ajustement de corrélation "taille de firme" (Art. 153(4)).

> **Limite assumée** : les montants du dataset restant tous < 1 M EUR, une PME y resterait en toute rigueur dans le portefeuille Retail (Art. 123). Le segment `CORPORATE_SME` est un choix pédagogique explicite.

Revenu mensuel et données PME (chiffre d'affaires, effectifs) sont simulés car absents de la base source mais indispensables au calcul des ratios d'endettement, à l'ajustement de corrélation PME, et — nouveauté de cette version — à la segmentation de population de la section 3.

Résultat sur le portefeuille simulé : `RETAIL_CONSUMER` 949 obligors (94,9 %), `RETAIL_SME` 34 (3,4 %), `CORPORATE_SME` 17 (1,7 %).

---

## 2. Chronologie et panel d'observations (`Tcg.py`) — CRR Art. 178

Deux notions de temps distinctes :

### A. Panel d'observations annuelles (calibration LRA)

La bonne pratique EBA GL/2017/16 observe chaque dossier à **plusieurs reprises au cours de sa vie** (anniversaires successifs), et teste à chaque point s'il fait défaut dans les 12 mois qui suivent CE point précis :

```
pour chaque dossier, tant qu'il est vivant et que la fenêtre est entièrement réalisée :
    t = originationDate, originationDate+12m, originationDate+24m, ...
    default12mFlag(t) = 1  si  t < defaultDate <= t + 12 mois   -> le dossier sort de la population, arrêt
    default12mFlag(t) = 0  si  aucun défaut dans (t, t+12 mois] ET le crédit est encore actif à t+12 mois
    (observation exclue si la fenêtre n'est pas encore entièrement réalisée à la date d'arrêté,
     ou si le crédit arrive à échéance avant la fin des 12 mois -> fenêtre censurée)
```

**Exemple concret** : origination en 2011, défaut en 2014. Observation 2011 (fenêtre 2011→2012) : `default12mFlag = 0`. Observation 2012 (fenêtre 2012→2013) : `default12mFlag = 0`. Observation 2013 (fenêtre 2013→2014) : défaut constaté → `default12mFlag = 1`, le dossier sort de la population. Ce dossier contribue ainsi correctement à la série de taux de défaut annuels, à la bonne année (2013), plutôt que de disparaître silencieusement.

Implémenté dans `buildAnnualPerformancePanel()`, qui produit un **panel** (plusieurs lignes par dossier). Sur le portefeuille simulé : 1 143 observations annuelles sur 774 dossiers actifs au moins une fois dans l'historique (2010–2023).

Un indicateur diagnostique `firstYearDefaultFlag` (défaut dans la 1ère année uniquement) est conservé à titre de comparaison dans les exports, mais **n'alimente plus la calibration LRA**.

### B. Statut du livre à la date d'arrêté (staging IFRS 9)
À la date de reporting (`OBSERVATION_DATE` = 2024-06-30), chaque dossier est classé `ACTIVE`, `DEFAULTED` ou `MATURED`. Seuls `ACTIVE` et `DEFAULTED` entrent dans le calcul de l'ECL. Un proxy d'arriérés (`daysPastDue`) est simulé pour le backstop des 30 jours de l'IFRS 9.

---

## 3. Segmentation de la POPULATION (`populationSegmentation.py`) — CRR Art. 170, NOUVEAU MODULE

### Justification

L'Art. 170 CRR exige une différenciation du risque fondée sur des caractéristiques **homogènes intra-classe**. Ce principe est appliqué ici en amont même de la notation de risque : deux obligors dont la capacité économique (revenu, qualification, endettement relatif) diffère fortement n'appartiennent pas à la même population statistique, et ne doivent donc pas être calibrés par le même modèle de PD — quand bien même ils recevraient, par ailleurs, le même grade de risque. Concrètement : un obligor à 1 000 EUR/mois et un obligor à 5 000 EUR/mois classés tous deux "veryLow" par leurs caractéristiques de risque propre (épargne, ancienneté, montant emprunté...) ne portent pas nécessairement la même PD réelle — leur robustesse face à un choc de revenu, leur reste-à-vivre, et donc leur probabilité de défaut future, diffèrent structurellement.

### Méthode

**Variables utilisées** (`POPULATION_SEGMENTATION_FEATURES`) : `monthlyIncomeEur`, `jobSkillLevel`, `creditToAnnualIncomeRatio`, `installmentToIncomeRatio` — exclusivement des variables de capacité économique, connues à l'octroi, distinctes des variables de risque pur utilisées à l'étape 4 (épargne, garantie logement...).

1. **Standardisation** (`StandardScaler`, moyenne 0, écart-type 1) des 4 variables.
2. **DBSCAN** (`eps=config.POPULATION_DBSCAN_EPS=1.5`, `min_samples=config.POPULATION_DBSCAN_MIN_SAMPLES=15`) détecte les profils atypiques (label `-1`), isolés en `populationOutlierReview` et exclus du KMeans.
3. **KMeans** (`k=config.N_POPULATION_SEGMENTS=3`, `n_init=20`, `random_state=42`) sur la population cœur.
4. Les clusters bruts sont classés par **revenu mensuel moyen croissant** et mappés vers `config.POPULATION_SEGMENT_LABELS_ORDERED = ["populationModeste", "populationIntermediaire", "populationAisee"]`.

### Choix de k=3

`N_POPULATION_SEGMENTS` est un paramètre de `config.py`. La valeur 3 a été retenue après comparaison du score de silhouette pour k ∈ {2, 3, 4, 5} sur la population cœur : k=3 offre un score de silhouette de 0,456 (bonne séparation) avec des effectifs raisonnablement équilibrés (631 / 209 / 145), contre un score plus faible et des groupes plus fragmentés au-delà. Un k plus élevé (5, par exemple) fragmenterait excessivement les cellules croisées avec les 5 grades de risque de la section 4 sur un portefeuille de seulement ~1000 obligors — arbitrage documenté ici plutôt que caché.

### Résultat sur le portefeuille simulé

| Population | Effectif | Revenu mensuel moyen | Qualification moyenne | Ratio d'endettement moyen |
|---|---|---|---|---|
| populationModeste | 209 | 1 498 EUR | 0,93 | 0,121 |
| populationIntermediaire | 631 | 2 285 EUR | 2,01 | 0,116 |
| populationAisee | 145 | 3 644 EUR | 2,98 | 0,125 |
| populationOutlierReview | 15 (1,5 %) | 1 455 EUR | 0,73 | **0,546** |

core (k=3, population Cible) = **0,456**. Les profils atypiques se distinguent nettement par un ratio d'endettement moyen presque 5 fois supérieur aux populations cible, cohérent avec l'objectif de la détection DBSCAN (profils économiquement incohérents).

> **Résultat ** : une ANOVA (section 4) montre que `populationSegment` seul n'explique pas significativement `defaultEverFlag` sur ce portefeuille (F=0,60, p=0,55, η²=0,001). Ce n'est PAS l'objectif de cette étape populationSegmentation.py ne construit rien à partir du défaut — mais cela doit être lu honnêtement : la segmentation de population sert la validité statistique de la calibration (section 5), pas à elle seule la discrimination du risque.

---

## 4. Classes de risque par ALGORITHME DE BELSON (`riskClustering.py`) — CRR Art. 170

### Pourquoi remplacer le clustering non supervisé par une méthode supervisée

L'algorithme de Belson (D.J. Belson, *"Matching and Prediction on the Principle of Biological Classification"*, 1959), précurseur des méthodes AID/CHAID, construit au contraire les classes en utilisant directement le défaut observé comme critère de coupure — ce qui améliore mécaniquement la séparation des classes, au prix d'un risque de sur-apprentissage à surveiller (section 12).

### Algorithme

Exécuté **séparément pour chaque `populationSegment`** (hors `populationOutlierReview`, dont les obligors reçoivent directement `riskGradeClass = "outlierReview"`).

**Étape 1 — Sélection de la meilleure coupure à chaque nœud.** Pour un nœud (sous-ensemble d'obligors) et pour chaque variable candidate (`CLUSTERING_FEATURES` : `age`, `jobSkillLevel`, `savingAccountScore`, `checkingAccountScore`, `housingCollateralProxyScore`, `creditAmountScaledLog`, `durationMonths`, `installmentToIncomeRatio`, `creditToAnnualIncomeRatio`), on teste un ensemble de seuils candidats `s` (valeurs distinctes si la variable a peu de modalités, sinon jusqu'à `config.BELSON_MAX_CANDIDATE_THRESHOLDS=8` quantiles). Pour chaque coupure (variable, seuil), on construit la table de contingence 2×2 :

```
                défaut = 0   défaut = 1
gauche (<= s)      a            b
droite (> s)       c            d
```

et on calcule la statistique du Chi² d'indépendance (avec correction de continuité de Yates) :

```
chi2 = sum( (observe_ij - attendu_ij)^2 / attendu_ij )   pour i,j dans la table 2x2
attendu_ij = (somme_ligne_i * somme_colonne_j) / n_total
```

La coupure retenue est celle qui **maximise le Chi²** parmi toutes les variables et tous les seuils testés (sous contrainte `taille_gauche >= BELSON_MIN_LEAF_SIZE` et `taille_droite >= BELSON_MIN_LEAF_SIZE`, avec `BELSON_MIN_LEAF_SIZE=25`).

**Étape 2 — Critère d'arrêt.** Le nœud est scindé si et seulement si :
```
p_value(meilleure coupure) < config.BELSON_CHI2_PVALUE_THRESHOLD (=0.05)
ET profondeur < config.BELSON_MAX_DEPTH (=3)
ET taille du nœud >= 2 * BELSON_MIN_LEAF_SIZE
ET le nœud contient au moins un défaut et un non-défaut
```
Sinon, le nœud devient une feuille terminale. La profondeur maximale de 3 borne le nombre de feuilles à 2³=8 par population.

**Étape 3 — Fusion des feuilles en grades.** Les feuilles sont triées par taux de défaut observé croissant :
```
tauxDéfaut(feuille) = totalDéfauts(feuille) / effectif(feuille)
```
puis fusionnées itérativement : à chaque itération, on fusionne la paire de feuilles **adjacentes** (dans l'ordre trié) dont l'écart de taux de défaut est le plus faible, jusqu'à obtenir au plus `config.N_RISK_GRADES=5` groupes. La monotonie du taux de défaut par groupe final est garantie par construction (fusion d'éléments déjà triés). Si l'arbre produit moins de feuilles que 5, les étiquettes de grade sont échantillonnées parmi `["veryLow","low","medium","high","veryHigh"]` en conservant les deux extrêmes (`numpy.linspace` arrondi), pour ne pas artificiellement resserrer l'échelle de risque.

**Cas de repli** : si une population a moins de `2×BELSON_MIN_LEAF_SIZE` obligors ou ne contient qu'une seule valeur de `defaultEverFlag`, un grade unique (`medium`) lui est attribué, documenté comme limite.

### Résultat sur le portefeuille simulé

| Population | Feuilles Belson | Grades finaux |
|---|---|---|
| populationModeste (209) | 4 | 4 (veryLow 10,0 % — low 13,9 % — high 36,2 % — veryHigh 62,2 %, taux de défaut observés bruts) |
| populationIntermediaire (631) | 7 | 5 (veryLow 6,3 % — low 21,4 % — medium 27,7 % — high 49,7 % — veryHigh 83,3 %) |
| populationAisee (145) | 3 | 3 (veryLow 11,9 % — medium 32,0 % — veryHigh 52,8 %) |
| populationOutlierReview (15) | — | outlierReview (26,7 %) |

### Validation ANOVA (Art. 170 CRR)

Pour chaque `populationSegment`, une ANOVA à un facteur (`scipy.stats.f_oneway`) est menée sur `defaultEverFlag` groupé par `riskGradeClass` :

```
F = (SS_between / (k-1)) / (SS_within / (N-k))
SS_between = sum_i( n_i * (moyenne_i - moyenne_globale)^2 )        pour chaque groupe i
SS_within  = sum_i( sum_{x dans groupe i}( (x - moyenne_i)^2 ) )
eta2 = SS_between / (SS_between + SS_within)
```

Résultats sur le portefeuille simulé :

| Périmètre | F | p-value | η² |
|---|---|---|---|
| riskGradeClass au sein de populationModeste | 14,69 | < 0,0001 | 0,177 |
| riskGradeClass au sein de populationIntermediaire | 44,37 | < 0,0001 | 0,221 |
| riskGradeClass au sein de populationAisee | 9,84 | 0,0001 | 0,122 |
| populationSegment (diagnostic) | 0,60 | 0,550 | 0,001 |

Les trois premières lignes confirment une hétérogénéité inter-classe hautement significative (p < 0,001) à l'intérieur de chaque population, avec une taille d'effet modérée à substantielle (η² entre 0,12 et 0,22 — au sens des conventions usuelles de Cohen, un η² > 0,14 est considéré comme un effet "large"). La dernière ligne confirme, à titre diagnostique, que `populationSegment` seul n'est pas un facteur de risque significatif (cf. section 3) — cohérent avec le fait qu'il n'a pas été construit à cette fin.

> **Limite assumée** : parce que l'algorithme de Belson utilise `defaultEverFlag` pour choisir ses propres coupures, cette ANOVA est en partie mesurée **en échantillon** (in-sample) — une significativité élevée est structurellement plus facile à obtenir qu'avec une méthode non supervisée. La section 12 (Train/OOT) apporte un contrôle indépendant de cette limite.

---

## 5. PD Long Run Average — EBA GL/2017/16 (§88-94), CRR Art. 180

### Formule de base

```
PD_LRA_brute(population, grade) = moyenne_années( tauxDéfautAnnuel(population, grade, année) )   pour année ∈ [2010, 2023]
```

où `tauxDéfautAnnuel` provient du **panel d'observations annuelles** (section 2.A), désormais croisé par la **paire (populationSegment, riskGradeClass)** et non plus par le seul grade — traduction directe, au niveau du calcul, du principe de la section 3.

### Crédibilité actuarielle (nouveauté de cette version)

La stratification à trois facteurs (population × grade × année) fragmente le panel : certaines cellules ne comptent que quelques observations annuelles (ex. `populationModeste × veryLow` : 6 observations sur l'historique complet). Sur un échantillon aussi réduit, un taux de défaut brut de 0 % ou 100 % reflète le plus souvent le hasard d'échantillonnage plutôt qu'une vraie signature de risque, et contaminerait ensuite le contrôle de monotonie (une seule cellule extrême forcerait, par construction du Pool Adjacent Violators, la fusion de plusieurs grades voisins).

La correction retenue est la **crédibilité de Bühlmann**, technique actuarielle standard :

```
Z(cellule) = n(cellule) / ( n(cellule) + K )                    K = config.LRA_CREDIBILITY_K = 30

PD_LRA_credibilisée(population, grade) =
      Z(cellule) * PD_LRA_brute(population, grade)
    + (1 - Z(cellule)) * priorPopulation(population)

priorPopulation(population) = totalDéfauts(population) / totalObservations(population)
                              (agrégé sur TOUTES les cellules de grade de cette population)
```

Plus une cellule est documentée (n grand), plus `Z` se rapproche de 1 et plus son propre taux pèse ; plus elle est fine, plus `Z` se rapproche de 0 et plus elle est ramenée vers le taux moyen de sa population. Avec K=30 : une cellule à 6 observations (`populationModeste × veryLow`) a `Z ≈ 0,167`, et son taux brut de 100 % est ramené à environ 43 % (moyenne pondérée avec le prior de population, 31,6 %) ; une cellule à 216 observations (`populationIntermediaire × high`) a `Z ≈ 0,878`, quasiment inchangée par la crédibilisation (36,1 % brut → 34,5 % après crédibilité).

> Ce choix méthodologique n'est **pas** d'origine réglementaire (l'EBA GL/2017/16 n'impose pas de technique de crédibilisation nommément) : c'est une technique statistique standard, empruntée à la pratique actuarielle, mobilisée ici pour éviter qu'une PD LRA finale ne soit pilotée par 2-3 observations. Elle doit être documentée comme telle en gouvernance des modèles (MoC catégorie B, section 6).

### Contrôle de monotonie (Pool Adjacent Violators Algorithm)

```
Pour chaque populationSegment (hors populationOutlierReview), sur les grades ordonnés
[veryLow, low, medium, high, veryHigh] (grades présents uniquement) :
    tant qu'il existe i tel que PD(grade_i) > PD(grade_i+1) :
        PD(grade_i) = PD(grade_i+1) = moyenne( PD(grade_i), PD(grade_i+1) )
```
Appliqué **indépendamment à l'intérieur de chaque population** (la monotonie n'a de sens qu'entre grades d'une même population). `outlierReview` n'est jamais lissé.

### Résultat sur le portefeuille simulé (PD LRA finale, après crédibilité + monotonie)

| Population | veryLow | low | medium | high | veryHigh |
|---|---|---|---|---|---|
| populationAisee | 16,35 % | — | 16,89 % | — | 27,30 % |
| populationIntermediaire | 7,26 % | 22,46 % | 22,46 % | 34,47 % | 38,79 % |
| populationModeste | 31,08 % | 31,08 % | — | 34,99 % | 34,99 % |
| populationOutlierReview | — | — | 16,67 % (outlierReview) | — | — |

Des pooling résiduels subsistent (ex. `low = medium` chez populationIntermediaire, `veryLow = low` chez populationModeste) : ils traduisent une hétérogénéité insuffisante entre grades adjacents une fois les données stabilisées, cohérent avec la taille limitée de l'échantillon simulé (cf. section 13, limites).

### Tout ce qui découle de la LRA

- **MoC A** (section 6) est calculée comme un intervalle de confiance **autour** du point central `PD_LRA_credibilisée` — les deux corrections sont complémentaires, pas redondantes : la crédibilité stabilise le point central, la MoC A ajoute une marge de prudence autour de ce point stabilisé.
- **`pdFinalRegulatory` = PD_LRA + MoC_A + MoC_B + MoC_C** (section 6) est la PD utilisée telle quelle dans la **formule de capital IRB-A** (section 10, Art. 180(2) CRR : le capital réglementaire doit être calculé sur une PD TTC, jamais une PD PIT).
- **`pdOriginationGrade` (IFRS 9, section 9)** = `pdFinalRegulatory`, point de départ de la PD PIT et référence du déclenchement SICR (augmentation relative/absolue mesurée depuis cette PD d'origine).
- **Les tests de stress** (section 11) mesurent l'écart de la PD PIT (elle-même dérivée de `pdOriginationGrade`) sous un choc macroéconomique.
- **La validation** (section 12) mesure si le rang de `pdFinalRegulatory` par cellule sépare effectivement les bons et mauvais payeurs observés.

---

## 6. Marge de Conservatisme (MoC A / B / C) — EBA GL/2017/16 (§41-52), CRR Art. 179(1)(f)

La MoC est un **add-on additif** appliqué à la LRA, calculée au niveau de la **cellule (populationSegment, riskGradeClass)** :

```
PD_finale(cellule) = PD_LRA(cellule) + MoC_A(cellule) + MoC_B + MoC_C
```

| Catégorie | Nature | Implémentation |
|---|---|---|
| **MoC A** | Erreur d'estimation générale, par cellule | Intervalle de confiance de Wilson à 95 % sur le taux de défaut agrégé de la cellule ; `MoC_A = borne_supérieure − PD_LRA` |
| **MoC B** | Déficiences de données/méthode identifiées (dates simulées, revenu proxy, notation par DBSCAN/KMeans + Belson non supervisés/supervisés plutôt que jugement d'expert validé) | Add-on forfaitaire documenté (15 bps), à valider en comité des modèles |
| **MoC C** | Changements pertinents non encore reflétés dans la LRA | Population Stability Index (PSI) entre la distribution des **cellules (population × grade)** du millésime le plus récent et l'historique ; add-on proportionnel si PSI > 0,10 |

**Formule MoC A (intervalle de Wilson)** :
```
z = quantile_normal(1 - (1-0.95)/2)
p = totalDéfauts(cellule) / totalObservations(cellule) = n
centre = (p + z^2/(2n)) / (1 + z^2/n)
demi-largeur = z * sqrt( p(1-p)/n + z^2/(4n^2) ) / (1 + z^2/n)
borne_supérieure = centre + demi-largeur
MoC_A = max(borne_supérieure - PD_LRA(cellule), 0)
```

**Formule PSI (MoC C)** :
```
PSI = somme_cellules( (dist_récente - dist_historique) * ln(dist_récente / dist_historique) )
```
calculé sur la distribution des libellés combinés `populationSegment | riskGradeClass` (et non plus du seul grade).

### Résultat sur le portefeuille simulé

PSI = 0,1060 (> seuil d'alerte 0,10) → MoC C activée = 1,06 %. Exemple de décomposition : `populationModeste × veryLow` — PD_LRA 31,08 % + MoC A 68,92 % (cellule extrêmement fine, cf. section 5) + MoC B 0,15 % + MoC C 1,06 % → **PD finale plafonnée à 99,90 %** (borne haute du plafond `config`). Voir section 13 pour la lecture honnête de ce résultat.

---

## 7. LGD — méthode workout (`lgdEstimation.py`) — CRR Art. 181, EBA GL/2019/03

```
LGD_réalisée = 1 − [ VA(recouvrements) − coûts_directs − coûts_indirects ] / EAD_au_défaut
```

Les flux de recouvrement, leur délai et les coûts de gestion du contentieux sont simulés (fonction du collatéral proxy, du segment, avec bruit) puis actualisés au taux `RECOVERY_DISCOUNT_RATE_ANNUAL`. La **LGD downturn** (Art. 181(1)(b)) retient, par cellule **grade × perimeterSegment** (inchangé — la LGD n'est volontairement pas croisée avec `populationSegment`, voir limite ci-dessous), le plus conservateur entre la LGD moyenne tout-cycle et la LGD moyenne des seules années de choc.

> **Choix méthodologique documenté** : contrairement à la LRA (section 5), la LGD n'est pas recroisée avec `populationSegment`. Avec ~230 défauts simulés au total, un découpage supplémentaire (3 populations × 5 grades × 3 segments périmètre = jusqu'à 45 cellules) produirait des cellules à 2-5 défauts, statistiquement inexploitables pour une LGD. C'est un arbitrage explicite entre granularité et significativité statistique.

Résultat sur le portefeuille simulé : LGD réalisée moyenne 58,54 %, LGD downturn moyenne appliquée au livre 59,13 %.

---

## 8. EAD et CCF (`eadEstimation.py`) — CRR Art. 166

EAD = encours amorti à la date d'arrêté + `CCF × ligne hors bilan` pour le segment PME/Corporate. Les CCF appliqués sont indicatifs et à rapprocher, en production, des valeurs supervisées (F-IRB) ou des CCF internes validés (A-IRB). EAD totale du portefeuille simulé : 996 210.

---

## 9. Staging IFRS 9 et ECL (`ifrs9Staging.py`) — IFRS 9 §5.5, EBA GL/2016/07

La PD Through-The-Cycle (`pdFinalRegulatory`, section 5-6) sert au **capital réglementaire** (IRB). L'IFRS 9 exige une PD **Point-In-Time** (PIT), recalculée à chaque date de reporting :

```
PD_PIT = PD_origination × multiplicateur_macro × multiplicateur_arriérés × multiplicateur_backstop
```

Le SICR (§5.5.9) est détecté par un faisceau de 3 indices : augmentation relative de la PD ≥ ×2 depuis l'octroi, augmentation absolue ≥ 75 bps, backstop de 30 jours d'arriérés (§5.5.11).

| Stage | Condition | ECL |
|---|---|---|
| 1 | Sain, pas de SICR | PD 12 mois × LGD × EAD (actualisé) |
| 2 | SICR avéré | PD lifetime × LGD × EAD (actualisé) |
| 3 | Défaut constaté à l'arrêté | PD lifetime × LGD × EAD (actualisé) |

Résultat sur le portefeuille simulé : 382/1000 dossiers notés (98 ACTIVE + 284 DEFAULTED), dont Stage 1 = 90, Stage 2 = 8, Stage 3 = 284. ECL totale = 71 185.

---

## 10. Capital réglementaire IRB-A (`irbCapitalRwa.py`) — CRR Art. 153, 154, 162, 501

Formule de Bâle complète (et non `RWA ≈ 12,5×PD×LGD` simplifié) :

```
K = LGD × [ N( √(1/(1−R)) × G(PD) + √(R/(1−R)) × G(0,999) ) − PD ] × MA
RWA = K × 12,5 × EAD
```

- **Corrélation R** : Retail (Art. 154) via fonction exponentielle de la PD ; Corporate/PME-Corporate (Art. 153) avec ajustement taille de firme pour CA ∈ [5, 50] M EUR (Art. 153(4)).
- **Ajustement de maturité MA** (Corporate/PME-Corporate uniquement, Art. 162), non appliqué au Retail.
- **Facteur supportant PME** (Art. 501) : abattement de RWA (×0,7619) pour les expositions PME ≤ 50 M EUR de CA.

La PD utilisée est **`pdFinalRegulatory`**, jamais la PD PIT (Art. 180(2) CRR). Résultat sur le portefeuille simulé : RWA total 1 489 199, exigence Pilier 1 (8 %) 119 136, capital total requis (P1 + coussins) 171 258, corrélation moyenne appliquée 0,0320.

---

## 11. Tests de stress et stress test inverse (`stressTesting.py`) — CRR Art. 177, EBA GL/2018/04

### A. Tests de stress par scénario
Trois scénarios pondérés appliquent un choc relatif au taux de chômage utilisé dans la composante macro de la PD PIT :

| Scénario | Choc chômage | Poids | ECL stressée (portefeuille simulé) |
|---|---|---|---|
| Baseline | 0 % | 50 % | 71 185 |
| Upside | −20 % | 25 % | 46 407 (−34,8 %) |
| Downside | +35 % | 25 % | 137 041 (+92,5 %) |

### B. Stress test inverse (reverse stress test)
Recherche par bissection (`scipy.optimize.brentq`) du choc de chômage relatif au-delà duquel l'ECL du portefeuille noté dépasse le capital total requis (Pilier 1 + coussins) calculé au scénario central. Résultat sur le portefeuille simulé : point de rupture à **+50,8 %** de choc chômage relatif (taux de chômage simulé de rupture ≈ 7,39 %), pour un capital disponible de 171 258.

---

## 12. Validation statistique : Train/OOT, AUC, Gini, VIF, ANOVA (`modelValidation.py`) — EBA GL/2017/16 (validation)

### A. Score utilisé pour l'AUC/Gini — changement méthodologique

Le classement de risque provient désormais d'un système à deux niveaux (population + grade, sections 3-4) où le **même libellé de grade peut porter des PD différentes selon la population**. Le rang du libellé seul (0=veryLow...4=veryHigh) n'est donc plus un score valide : le score utilisé est le **rang dense de `pdFinalRegulatory` moyenne par cellule (populationSegment, riskGradeClass)**, croissant avec le risque.

### B. Découpage Train / Out-Of-Time (OOT)
Train = années de performance < `OOT_START_YEAR` (2022), OOT = années ≥ 2022.

**Limite assumée et amplifiée par rapport à la version précédente** : l'algorithme de Belson (section 4) utilise directement `defaultEverFlag`, calculé sur l'historique complet, pour construire les classes elles-mêmes (pas seulement pour les ordonner, comme le faisait l'ancien KMeans). Le découpage Train/OOT mesure donc, plus encore qu'avant, la **stabilité** du pouvoir discriminant dans le temps plutôt qu'une validation hors échantillon au sens strict. Un raffinement futur consisterait à reconstruire l'arbre de Belson en n'utilisant que les défauts antérieurs à `OOT_START_YEAR`.

### C. AUC et Gini (pouvoir discriminant)

| Échantillon | Observations | Taux de défaut | AUC | Gini |
|---|---|---|---|---|
| Ensemble du panel | 1 143 | 23,5 % | 0,699 | 0,398 |
| Train (< 2022) | 939 | 23,6 % | 0,703 | 0,406 |
| Out-Of-Time (≥ 2022) | 204 | 23,0 % | 0,686 | 0,373 |

**Lecture honnête** : le Gini passe de ≈ 0,04 (ancienne méthode, clustering non supervisé pur) à ≈ 0,40 (méthode actuelle, Belson supervisé + population homogène). C'est une amélioration substantielle, en grande partie mécanique (le point A ci-dessus l'explique). Le résultat rassurant est que le Gini **OOT (0,373) reste proche du Gini Train (0,406)** — une perte de pouvoir discriminant hors échantillon aurait signalé un sur-apprentissage sévère ; ce n'est pas le cas ici, même si ce test ne remplace pas une reconstruction complète de l'arbre sur le seul Train (limite ci-dessus).

### D. VIF (colinéarité des variables de segmentation)

Calculé désormais séparément pour les deux jeux de variables (population et risque) :

| Module | Variable | VIF |
|---|---|---|
| populationSegmentation | monthlyIncomeEur | 2,88 |
| populationSegmentation | jobSkillLevel | 2,87 |
| populationSegmentation | installmentToIncomeRatio | 1,74 |
| populationSegmentation | creditToAnnualIncomeRatio | 1,73 |
| riskClustering/Belson | creditToAnnualIncomeRatio | 6,61 ⚠ |
| riskClustering/Belson | creditAmountScaledLog | 4,11 |
| riskClustering/Belson | installmentToIncomeRatio | 3,06 |
| riskClustering/Belson | durationMonths | 2,49 |
| riskClustering/Belson | jobSkillLevel | 1,50 |
| riskClustering/Belson | age, housingCollateralProxyScore, savingAccountScore, checkingAccountScore | ~1,0 |

`creditToAnnualIncomeRatio` dépasse le seuil de 5 dans le jeu de variables de risque (inchangé depuis la version précédente) : mécaniquement corrélée à `creditAmountScaledLog`, `installmentToIncomeRatio` et `durationMonths`.

### E. ANOVA (homogénéité intra-classe / hétérogénéité inter-classe)

Voir section 4 pour le détail des formules et résultats (F, p-value, η² par population, et diagnostic sur `populationSegment`).

---

## 13. Limites connues et pistes d'amélioration (transparence de validation)

- Le pouvoir discriminant du grade (Gini ≈ 0,40) est désormais honorable pour ce jeu de données, mais reste construit **en partie in-sample** par l'algorithme de Belson (section 4/12.B) : la stabilité Train/OOT est rassurante mais ne remplace pas une reconstruction complète hors échantillon.
- La cellule `populationModeste × veryLow` (6 observations panel) illustre la limite structurelle d'un découpage à trois facteurs (population × grade × année) sur un historique de ~1000 obligors : malgré la crédibilité de Bühlmann (section 5), sa MoC A reste très large et sa PD finale est plafonnée au maximum autorisé (section 6). En production, une cellule aussi peu documentée serait fusionnée avec une classe voisine ou laissée hors notation individuelle jusqu'à accumulation d'historique suffisant.
- Le silhouette score du clustering de population (0,456) indique une séparation correcte à bonne ; celui de l'ancien clustering de risque (0,18-0,25, remplacé par Belson) n'est plus pertinent, Belson n'étant pas évalué par silhouette (méthode supervisée).
- Une variable (`creditToAnnualIncomeRatio`) présente un VIF > 5 dans le jeu de variables de risque (section 12.D) : redondance avec d'autres variables dérivées du montant de crédit, inchangée depuis la version précédente.
- La LGD n'est pas croisée avec `populationSegment` (section 7), choix documenté de limitation de la sparsité des cellules.
- La crédibilité actuarielle (Bühlmann, section 5) et l'algorithme de Belson (section 4) sont des techniques statistiques/actuarielles standard, mais ne sont **pas nommément prescrites** par les guidelines EBA citées : leur usage doit être documenté et validé en comité des modèles comme toute méthode non explicitement mandatée par le texte réglementaire.
- Les données temporelles, PME, de recouvrement et de coûts sont simulées : ce projet est une démonstration méthodologique de bout en bout, pas un modèle validé sur données réelles.
- Le segment `CORPORATE_SME` est une construction pédagogique (cf. section 1) à ne pas reproduire telle quelle en production sans revalider le seuil Art. 123.

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

- **EBA/GL/2017/16** — *Guidelines on PD estimation, LGD estimation and the treatment of defaulted exposures*, publiées novembre 2017, application au 1er janvier 2021. Base de la calibration LRA et de la MoC A/B/C (sections 5 et 6).
- **EBA/GL/2019/03** — *Guidelines for the estimation of LGD appropriate for an economic downturn ('Downturn LGD estimation')*, publiées le 6 mars 2019, application au 1er janvier 2021. Base de la LGD downturn (section 7).
- **EBA/GL/2016/07** — *Guidelines on the application of the definition of default under Article 178 of Regulation (EU) No 575/2013*, publiées le 28 septembre 2016, application au 1er janvier 2021. Base de la définition du défaut (Glossaire, section 2).
- **EBA/GL/2018/04** — *Guidelines on institutions' stress testing*, application au 1er janvier 2019, dans le cadre de l'ICAAP (Art. 73 CRD IV). Base des tests de stress et du stress test inverse (section 11).

### Norme comptable

- **IFRS 9** — *Financial Instruments*, publiée par l'IASB le 24 juillet 2014, effective de manière obligatoire depuis le 1er janvier 2018, adoptée dans l'UE par le règlement (UE) 2016/2067. §5.5 (dépréciation/ECL) est la base des sections 9 et 11.

### Techniques statistiques et actuarielles (non réglementaires, bonnes pratiques de modélisation)

- **Belson, D.J. (1959)** — *"Matching and Prediction on the Principle of Biological Classification"*, Journal of the Royal Statistical Society, Series C. Base de l'algorithme de segmentation binaire récursive supervisée (section 4).
- **Théorie de la crédibilité de Bühlmann** — technique actuarielle classique de pondération d'une estimation de segment fin par un facteur croissant avec sa taille d'échantillon (section 5), largement utilisée en tarification assurance et transposée ici à la stabilisation de la LRA.
- **Cohen, J. (1988)** — *Statistical Power Analysis for the Behavioral Sciences* — conventions usuelles de lecture de la taille d'effet η² (section 4).
