"""
=============================================================
⚙️ CONFIG.PY — Job Search Configuration
=============================================================

Edit this file to change what jobs the system looks for.

=============================================================
"""


# ----- YOUR CAREER PATHS (in priority order) -----
CAREER_PATHS = [
    {
        "name": "Data & Business Analytics",
        "queries": [
            "Data Analyst",
            "Analista de Dados",
            "Business Analyst",
            "Analista de Negócios",
            "Product Analyst"
        ],
    },
    {
        "name": "Product & CX Operations",
        "queries": [
            "Product Operations",
            "Product Ops",
            "Operations Analyst",
            "Analista de Operações",
            "Revenue Operations"
        ],
    },
    {
        "name": "Product Management",
        "queries": [
            "Product Manager",
            "Associate Product Manager",
            "Product Owner",
            "Growth Analyst"
        ],
    },
]


# ----- LOCATION SETTINGS -----
# We search specifically for São Paulo
LOCATIONS = [
    "São Paulo, Brazil",
]

INCLUDE_REMOTE = True





# ----- RECENCY FILTER -----
MAX_DAYS_OLD = 7

# ----- RESULTS SETTINGS -----
RESULTS_PER_QUERY = 100
MIN_MATCH_SCORE = 0
