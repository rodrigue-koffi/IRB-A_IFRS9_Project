# Méthodologie du projet — Modèle IRB-A / IFRS 9, expliquée sans formule

**Auteur du projet :** Rodrigue KOFFI
**Objet de ce document :** expliquer, étape par étape et en langage courant, ce que fait chaque module du pipeline et pourquoi il existe. Aucune formule mathématique n'est utilisée ici : pour le détail des calculs, des hypothèses et des articles réglementaires, se reporter à `docs/METHODOLOGY.md` (version technique).

---

## Pourquoi ce document existe

Le pipeline calcule, pour un portefeuille de crédits, une note de risque pour chaque emprunteur, un niveau de capital réglementaire à détenir (IRB-A) et une provision comptable (IFRS 9). Quinze étapes s'enchaînent, toujours dans le même ordre — celui du cycle de vie réel d'un crédit dans une banque : on charge les données, on définit le périmètre, on reconstitue les dates, on construit des variables, on classe les emprunteurs, on calibre une probabilité de défaut, on ajoute des marges de prudence, on estime la perte en cas de défaut et l'exposition, on calcule la provision comptable et le capital, on teste la résistance du portefeuille à une crise, on vérifie que le système de notation fonctionne, et on exporte tout dans un classeur.

Une attention particulière est portée, à la fin de ce document, à la **PD Long Run Average (LRA)** : c'est le chiffre central de tout le pipeline, celui dont dépendent directement le capital réglementaire et, indirectement, la provision comptable.

---

## Étape 1 — Chargement des données (`dataIngestion.py`)

On part d'un jeu de données public (German Credit Data, 1 000 dossiers de crédit à la consommation) et on le nettoie : les noms de colonnes sont traduits en anglais explicite, chaque dossier reçoit un identifiant stable, et les valeurs manquantes des comptes d'épargne/courants sont recodées en catégorie « aucun compte » plutôt que d'être traitées comme des données inconnues — parce que dans ce jeu de données, une valeur manquante à cet endroit *signifie* littéralement que la personne n'a pas ce type de compte.

## Étape 2 — Périmètre (`perimeterDefinition.py`)

Avant de noter qui que ce soit, une banque doit savoir *qui* elle note. On répartit donc chaque dossier entre trois catégories : particulier (Retail), petite entreprise restant dans le portefeuille Retail (Retail-SME) et petite entreprise traitée comme un portefeuille Corporate (Corporate-SME, créé ici uniquement pour illustrer certains mécanismes réglementaires propres aux entreprises). Le revenu mensuel de chaque particulier est également estimé à cette étape (il n'existe pas dans les données source) : c'est cette variable qui permettra, à l'étape 5, de distinguer les profils économiques.

## Étape 3 — Chronologie (`Tcg.py`)

Le jeu de données ne contient aucune date : ce module en fabrique une. Chaque dossier reçoit une date d'octroi, une date d'échéance, et — pour les dossiers qui ont fait défaut — une date de défaut plausible.

Le point le plus important de cette étape est la construction d'un **panel d'observations annuelles**. Au lieu de regarder un crédit une seule fois (à l'octroi, sur les douze premiers mois), on regarde chaque crédit encore vivant à *chaque anniversaire* de sa vie (1 an, 2 ans, 3 ans...) et on se demande, à chaque anniversaire : « ce crédit fait-il défaut dans les douze mois qui suivent ce point précis ? ». Un crédit accordé en 2011 et qui fait défaut en 2014 aurait été invisible dans une lecture « à l'octroi seulement » (il aurait semblé sain en 2011-2012) ; avec le panel, il est correctement comptabilisé comme un défaut à l'observation de 2013. C'est cette construction qui rend possible un calcul fiable de la LRA (voir plus loin).

## Étape 4 — Construction des variables de risque (`featureEngineering.py`)

On transforme les données brutes en variables utilisables : les niveaux d'épargne/compte courant deviennent des scores numériques, le type de logement devient un indicateur de garantie, des ratios d'endettement sont calculés (montant du crédit rapporté au revenu annuel, mensualité rapportée au revenu mensuel). Règle stricte respectée ici : on n'utilise que des informations connues **au moment de l'octroi** — utiliser une information connue seulement après coup (par exemple des impayés constatés plus tard) créerait un biais qui rendrait le modèle inutilisable en conditions réelles.

## Étape 5 — Segmentation de la population (`populationSegmentation.py`) — NOUVEAU

C'est ici que se traduit une idée simple mais essentielle : **une personne avec un revenu confortable et une personne au revenu proche du minimum n'appartiennent pas au même univers économique, et ne doivent donc pas être notées avec le même modèle de probabilité de défaut.** Mélanger les deux profils dans un seul calcul reviendrait à leur appliquer, de fait, une moyenne qui ne représente correctement ni l'un ni l'autre.

Concrètement, un algorithme (DBSCAN) commence par repérer les profils économiques atypiques (par exemple un ratio d'endettement incohérent avec le revenu déclaré) et les met de côté dans un groupe « à revoir manuellement », plutôt que de les forcer dans une catégorie qui ne leur correspond pas. Un second algorithme (KMeans) regroupe ensuite le reste du portefeuille en trois populations homogènes de capacité économique, classées de la plus modeste à la plus aisée sur la base du revenu, de la qualification professionnelle et des ratios d'endettement.

Sur le portefeuille étudié, cela donne trois populations : une population modeste (revenu moyen d'environ 1 500 €/mois, 209 emprunteurs), une population intermédiaire (environ 2 285 €/mois, 631 emprunteurs) et une population aisée (environ 3 644 €/mois, 145 emprunteurs), plus un petit groupe de 15 profils atypiques mis en revue séparée. La séparation entre ces trois groupes est nette (un indicateur de qualité de regroupement, le score de silhouette, atteint 0,46, ce qui est considéré comme une bonne séparation).

**Point important, honnêtement rapporté** : cette segmentation par revenu n'a *pas* pour objectif de prédire directement le risque de défaut (une vérification statistique, présentée à l'étape 6, montre d'ailleurs que le revenu seul n'explique pas significativement le taux de défaut sur ce portefeuille). Son objectif est différent et plus fondamental : garantir que chaque modèle de probabilité de défaut est calibré sur une population statistiquement cohérente, condition nécessaire à la validité de tout calcul de probabilité qui suit.

## Étape 6 — Classes de risque par algorithme de Belson (`riskClustering.py`) — NOUVEAU

Une fois la population scindée en trois groupes homogènes, on construit, **séparément à l'intérieur de chacun**, les classes de risque proprement dites (de « très faible risque » à « très fort risque »).

La méthode utilisée est l'**algorithme de Belson** (une technique ancienne, ancêtre des arbres de décision modernes comme CHAID, historiquement utilisée dans les grilles de score françaises). Contrairement au regroupement utilisé à l'étape précédente, celui-ci regarde directement qui a fait défaut : à chaque étape, il cherche, parmi toutes les caractéristiques disponibles (âge, épargne, montant du crédit, durée, ratios d'endettement...), la coupure qui sépare le mieux les bons et les mauvais payeurs, puis répète l'opération sur chacun des deux groupes ainsi formés, jusqu'à ce qu'il n'y ait plus de coupure suffisamment fiable statistiquement, ou qu'une profondeur maximale soit atteinte. Le résultat est un petit arbre de décision propre à chaque population, dont les feuilles (groupes finaux) sont ensuite regroupées, en respectant leur ordre de risque croissant, jusqu'à obtenir au maximum cinq classes par population : très faible, faible, moyen, élevé, très élevé.

Parce que cette méthode utilise directement l'information de défaut pour construire les classes, elle sépare beaucoup mieux les bons et les mauvais dossiers qu'un simple regroupement statistique — mais elle appelle aussi une vigilance particulière : un modèle qui « connaît la réponse » pendant sa construction peut sur-apprendre les particularités de l'historique utilisé plutôt que la vraie logique du risque. C'est précisément ce que la vérification de l'étape 14 (Train / Out-of-Time) permet de contrôler.

**Vérification de qualité (ANOVA)** : une fois les classes construites, un test statistique (analyse de variance) vérifie que les classes diffèrent bien significativement les unes des autres en taux de défaut, à l'intérieur de chaque population. Sur le portefeuille étudié, ce test est positif et net dans les trois populations (différences hautement significatives), ce qui confirme que la segmentation en classes homogènes de risque exigée par la réglementation (Art. 170 CRR) est effectivement atteinte.

## Étape 7 — Calibration de la PD Long Run Average (`pdCalibration.py`) — SECTION APPROFONDIE

*(voir la section dédiée à la fin de ce document — c'est le cœur du dispositif)*

## Étape 8 — Marge de Conservatisme (`marginOfConservatism.py`)

Aucune probabilité estimée sur un échantillon n'est parfaitement exacte : il faut donc ajouter une marge de prudence. Cette marge est décomposée en trois blocs qui s'additionnent :
- une marge liée à l'**incertitude statistique** : plus une classe de risque repose sur peu d'observations, plus cette marge est grande (elle se calcule au niveau le plus fin — chaque combinaison population × grade — plutôt qu'au niveau global) ;
- une marge **forfaitaire**, qui couvre les faiblesses connues et documentées de la méthode (dates simulées, revenu estimé, notation par apprentissage automatique plutôt que par expert) ;
- une marge liée à un **changement de composition du portefeuille** : si la répartition récente des dossiers entre populations et classes de risque s'écarte sensiblement de l'historique utilisé pour calibrer la LRA, une marge additionnelle est déclenchée. Sur le portefeuille étudié, cet écart dépasse le seuil d'alerte et une marge (modeste) est activée.

La probabilité finale utilisée pour le capital réglementaire est la somme de la LRA et de ces trois marges.

## Étape 9 — Estimation de la LGD (`lgdEstimation.py`)

Pour chaque dossier en défaut, on simule un montant recouvré, un délai de recouvrement et des coûts de gestion du contentieux, puis on en déduit la part réellement perdue (LGD). Cette perte est en moyenne de 58,5 % sur les dossiers en défaut simulés. On calcule ensuite, pour chaque combinaison classe de risque × type de portefeuille, une LGD « de crise » (downturn) : la plus prudente entre la moyenne habituelle et la moyenne observée sur les seules années de choc économique — cette LGD de crise est celle réellement appliquée à l'ensemble du livre, y compris aux dossiers encore sains.

## Étape 10 — Exposition au défaut (`eadEstimation.py`)

On calcule le capital restant dû de chaque crédit à la date d'arrêté (par un amortissement linéaire simplifié), auquel s'ajoute, pour les PME, une fraction convertie d'une ligne de crédit hors bilan (facteur de conversion en crédit, propre à chaque type de financement).

## Étape 11 — Notation IFRS 9 (`ifrs9Staging.py`)

Le capital réglementaire (étape 12) utilise une probabilité de défaut « à travers le cycle » (LRA + marges) — stable, peu sensible à la conjoncture du moment. La norme comptable IFRS 9 exige au contraire une probabilité « au moment présent » (Point-in-Time), qui reflète les conditions actuelles. Cette étape ajuste donc la PD d'octroi selon la conjoncture macroéconomique courante et selon le comportement récent de paiement du client (arriérés), puis classe chaque dossier en trois catégories (Stage 1 : sain, Stage 2 : dégradation significative du risque, Stage 3 : déjà en défaut), qui déterminent l'horizon sur lequel la perte attendue (ECL) est calculée. Sur le portefeuille étudié, l'ECL totale s'élève à environ 71 200.

## Étape 12 — Capital réglementaire IRB-A (`irbCapitalRwa.py`)

On calcule ici le montant de capital que la banque doit détenir en réserve pour ce portefeuille, selon la formule réglementaire complète de Bâle (et non une approximation simplifiée) : elle prend en compte la probabilité de défaut, la perte en cas de défaut, une corrélation entre les emprunteurs (différente pour les particuliers et pour les entreprises) et, pour les entreprises, un ajustement lié à la durée résiduelle du crédit. Un allègement spécifique est appliqué aux petites entreprises, conformément à l'objectif réglementaire de soutien au financement des PME. Sur le portefeuille étudié, le capital total requis (exigence de base + coussins) s'élève à environ 171 300.

## Étape 13 — Tests de résistance (`stressTesting.py`)

On rejoue trois scénarios macroéconomiques pondérés (central, favorable, défavorable) pour mesurer l'impact d'une dégradation du contexte économique sur la perte attendue. Puis, à l'inverse, on cherche directement *quel* niveau de choc économique suffirait à faire dépasser à la perte attendue le capital disponible de la banque : sur ce portefeuille, ce point de rupture se situe autour d'un choc de +51 % du taux de chômage relatif.

## Étape 14 — Validation du système de notation (`modelValidation.py`)

On vérifie ici que le système de notation fonctionne réellement, avec trois contrôles :
- **Pouvoir de discrimination (AUC/Gini)** : le système sépare-t-il correctement, dans les faits, les bons et les mauvais payeurs ? Avec la nouvelle méthode (population + Belson), l'indicateur Gini passe d'environ 0,04 (quasiment aucun pouvoir discriminant, obtenu avec l'ancienne méthode par regroupement non supervisé pur) à environ 0,40 — une amélioration importante. Point de vigilance honnête : comme la méthode de construction des classes utilise déjà l'information de défaut (voir étape 6), ce chiffre est en partie « acquis par construction ». La vérification suivante permet néanmoins de le relativiser favorablement : mesuré séparément sur la période récente non utilisée en priorité pour construire l'historique (2022 et après), le Gini reste à 0,37 — proche du chiffre global, ce qui est plutôt rassurant sur la stabilité du système dans le temps, même si ce n'est pas, formellement, un test hors-échantillon complet.
- **Stabilité dans le temps (Train / Out-of-Time)** : voir ci-dessus.
- **Redondance des variables (VIF)** : on vérifie qu'aucune variable utilisée pour segmenter le portefeuille n'est simplement une resucée d'une autre. Une variable (le ratio crédit/revenu annuel) dépasse légèrement le seuil d'alerte usuel, un point à surveiller documenté depuis la version précédente du projet.

## Étape 15 — Export des résultats (`reporting.py`)

Toutes les données et tous les résultats intermédiaires sont exportés dans un classeur Excel à quatorze onglets, exploitable directement pour une revue de comité des modèles ou pour un tableau de bord.

---

## Section approfondie — La PD Long Run Average (LRA)

### Qu'est-ce que la LRA, et pourquoi ce chiffre est-il si important ?

La LRA (*Long Run Average*, moyenne de long terme) est la probabilité de défaut « à travers le cycle » de chaque classe de risque : au lieu de mesurer le taux de défaut observé sur une seule année (qui peut être une bonne année ou une mauvaise année), on fait la moyenne du taux de défaut observé sur **toutes les années disponibles**, de manière à obtenir un chiffre représentatif d'un cycle économique complet, incluant aussi bien les années normales que les années de choc.

C'est ce chiffre — pas la probabilité « du moment » — qui sert de base au calcul du capital réglementaire. La raison est simple : si la banque recalculait son capital exigé à chaque fois que la conjoncture s'améliore ou se dégrade, elle devrait détenir moins de capital juste avant une crise (quand la conjoncture est encore bonne) et beaucoup plus de capital pendant la crise (au moment où c'est le plus difficile d'en trouver) — un mécanisme pro-cyclique qui amplifierait les crises au lieu de les amortir. La LRA sert précisément à éviter cela : elle donne un socle de capital stable, indépendant du cycle économique du moment.

### Comment la LRA est-elle construite dans ce projet ?

1. **Le panel d'observations annuelles** (construit à l'étape 3) est la matière première : chaque dossier de crédit y apparaît autant de fois qu'il a connu d'anniversaires vivants, avec, à chaque anniversaire, une réponse « a fait défaut dans les 12 mois qui suivent : oui/non ».
2. Pour chaque combinaison (population, classe de risque), on calcule le taux de défaut de **chaque année** de performance disponible (jusqu'à 14 années, de 2010 à 2023, couvrant deux années de choc identifiées, 2012 et 2020), puis on fait la **moyenne simple de ces taux annuels** — et non une moyenne pondérée par le nombre d'observations de chaque année. Ce choix est volontaire : une moyenne pondérée écraserait le poids des années de crise, qui comptent structurellement moins d'observations (les nouveaux crédits sont plus rares pendant une crise), ce qui irait à l'encontre de l'objectif même de représentativité du cycle.
3. **Nouveauté de cette version — la crédibilité actuarielle.** Découper le portefeuille en (population × classe de risque × année) peut produire des cases très peu peuplées : par exemple, la classe « risque très faible » de la population modeste ne compte que 6 observations annuelles au total sur les 14 années. Sur un échantillon aussi réduit, un taux de défaut de 0 % ou de 100 % est le plus souvent le fruit du hasard plutôt qu'un vrai signal de risque — et pourtant, sans correction, un chiffre aussi extrême finirait par contaminer tout le calcul de la classe. La solution retenue est empruntée à la théorie actuarielle de la crédibilité : chaque case est ramenée vers le taux de défaut moyen de *sa population* (pas de tout le portefeuille), avec un poids proportionnel à sa propre taille d'échantillon — plus une case dispose de données, plus son propre chiffre pèse lourd dans le résultat final ; plus elle est petite, plus elle est « tirée » vers la moyenne de sa population. Dans l'exemple ci-dessus, le taux brut de 100 % est ainsi ramené à un niveau beaucoup plus raisonnable (autour de 43 %) avant la suite du calcul.
4. **Contrôle de cohérence (monotonie).** Une fois les taux stabilisés, on vérifie qu'à l'intérieur de chaque population, le risque croît bien régulièrement d'une classe à l'autre (très faible < faible < moyen < élevé < très élevé). Si deux classes voisines s'inversent (souvent un signe de bruit statistique résiduel), elles sont fusionnées en une valeur commune, jusqu'à ce que l'ordre soit rétabli. C'est une exigence explicite de la réglementation (Art. 170 CRR).
5. Le résultat final est une PD LRA propre à **chaque combinaison (population, classe de risque)** — et non plus une PD par classe de risque seule, comme dans la version précédente du projet. C'est la traduction concrète, au niveau du chiffre final, du principe qui a motivé la création de l'étape 5 : deux emprunteurs classés tous deux « risque très faible » mais appartenant à des populations économiques différentes ne reçoivent pas nécessairement la même probabilité de défaut.

### Tout ce qui dépend de la LRA

La LRA n'est pas un résultat isolé : elle irrigue presque tout le reste du pipeline.

- **La Marge de Conservatisme (étape 8)** est un ajout appliqué directement par-dessus la LRA — elle ne se substitue jamais à elle, elle vient l'entourer d'une marge de prudence supplémentaire.
- **La PD finale réglementaire** (LRA + marges) est la valeur utilisée telle quelle dans la **formule de capital IRB-A** (étape 12) : la réglementation impose explicitement d'utiliser une PD à travers le cycle pour le capital, jamais une PD instantanée.
- **La PD d'octroi utilisée en IFRS 9** (étape 11) est également cette même PD finale réglementaire, prise comme point de départ avant d'être ajustée à la conjoncture actuelle pour obtenir la PD « du moment ». Le déclenchement du passage en Stage 2 (dégradation significative du risque) se mesure d'ailleurs comme un écart *par rapport à cette PD d'octroi* — donc, indirectement, par rapport à la LRA.
- **Les tests de résistance** (étape 13) partent eux aussi de cette même chaîne de calcul : ils mesurent de combien la PD « du moment » s'écarterait de son niveau actuel sous un choc macroéconomique donné.
- **La validation du système** (étape 14) mesure, en dernier ressort, si le classement des classes de risque produit par la LRA sépare effectivement les bons et les mauvais payeurs dans la réalité observée.

### Limite assumée sur la LRA, dans ce projet précis

Le jeu de données source ne couvre qu'un peu plus de 1 000 dossiers de crédit, répartis sur trois populations, cinq classes de risque possibles et quatorze années : certaines cases du calcul (comme l'exemple de 6 observations cité plus haut) restent fragiles malgré la correction de crédibilité, et se traduisent, à l'étape suivante (Marge de Conservatisme), par une marge de prudence très large — au point, pour la case la plus fragile du portefeuille étudié, de plafonner la PD finale au maximum autorisé. C'est un résultat honnête et attendu compte tenu de la taille de l'échantillon : dans un contexte réel, une case aussi peu documentée ne serait pas gérée seule, elle serait fusionnée avec une classe voisine, ou la population correspondante attendrait d'accumuler davantage d'historique avant d'être notée séparément.
