"""
config.py
Configuration centrale du pipeline IRB-A / IFRS9.
Auteur : Rodrigue KOFFI
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = ROOT_DIR / "data" / "raw"
DATA_PROCESSED_DIR = ROOT_DIR / "data" / "processed"
OUTPUT_DIR = ROOT_DIR / "output"
DOCS_DIR = ROOT_DIR / "docs"

RAW_FILE_NAME = "german_credit_data.xlsx"
RAW_SHEET_NAME = "german_credit_data(1)"

RANDOM_SEED = 42

VINTAGE_YEAR_MIN = 2010
VINTAGE_YEAR_MAX = 2023
DOWNTURN_YEARS = [2012, 2020]
OBSERVATION_DATE = "2024-06-30"
PERFORMANCE_WINDOW_MONTHS = 12

RETAIL_ART123_EXPOSURE_THRESHOLD_EUR = 1000000

SME_TURNOVER_MIN_EUR = 2000000
SME_TURNOVER_MAX_EUR = 50000000
SME_CORREL_TURNOVER_FLOOR_MEUR = 5
SME_CORREL_TURNOVER_CAP_MEUR = 50

SME_TARGET_SHARE = 0.14

N_RISK_GRADES = 5
RISK_GRADE_LABELS_ORDERED = ["veryLow", "low", "medium", "high", "veryHigh"]
DBSCAN_EPS = 2.2
DBSCAN_MIN_SAMPLES = 15
KMEANS_N_INIT = 20

MOC_A_CONFIDENCE_LEVEL = 0.95
MOC_B_FLAT_ADDON = 0.0015
MOC_C_PSI_ALERT_THRESHOLD = 0.10

DIRECT_COST_RATE_OF_EAD = 0.03
INDIRECT_COST_RATE_OF_EAD = 0.015
RECOVERY_DISCOUNT_RATE_ANNUAL = 0.05
RECOVERY_HORIZON_MONTHS_MIN = 6
RECOVERY_HORIZON_MONTHS_MAX = 36

SICR_RELATIVE_PD_MULTIPLE = 2.0
SICR_ABSOLUTE_PD_DELTA = 0.0075
SICR_BACKSTOP_DAYS_PAST_DUE = 30

PILLAR1_MIN_CAPITAL_RATIO = 0.08
CAPITAL_CONSERVATION_BUFFER = 0.025
CCYB_BUFFER = 0.01
SME_SUPPORTING_FACTOR = 0.7619

# ------------------------------------------------------------------
# Tests de stress (module stressTesting) - Art. 177 CRR
# ------------------------------------------------------------------
STRESS_SCENARIOS = {
    "Baseline": {"unemploymentShock": 0.0, "weight": 0.50},
    "Upside": {"unemploymentShock": -0.20, "weight": 0.25},
    "Downside": {"unemploymentShock": 0.35, "weight": 0.25},
}
REVERSE_STRESS_SHOCK_SEARCH_MAX = 20.0  # borne haute de recherche (choc chomage relatif, +2000%)

# --- Validation du modele (train / out-of-time, pouvoir discriminant) ---
# Annees de performance (performanceYear) considerees comme "hors echantillon"
# pour le test de stabilite du pouvoir discriminant. Les annees strictement
# anterieures forment l'echantillon "train" (in-sample).
OOT_START_YEAR = 2022
