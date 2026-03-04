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
            "CX Ops",
            "Analista de Operações"
        ],
    },
]


# ----- LOCATION SETTINGS -----
# We search specifically for São Paulo
LOCATIONS = [
    "São Paulo, Brazil",
]

INCLUDE_REMOTE = True


# ----- SÃO PAULO METROPOLITAN AREA FILTER -----
# After search, we REJECT jobs outside these cities.
# This solves the problem of getting results from
# Natal/RN, Blumenau/SC, Gov. Valadares/MG, etc.
SP_METRO_CITIES = [
    "são paulo", "sp", "guarulhos", "osasco", "barueri",
    "santo andré", "são bernardo do campo", "diadema",
    "mauá", "carapicuíba", "cotia", "taboão da serra",
    "itaquaquecetuba", "suzano", "ferraz de vasconcelos",
    "embu das artes", "itapevi", "franco da rocha",
    "francisco morato", "poá", "arujá", "santana de parnaíba",
    "jundiaí", "alphaville", "campinas",  # close enough to commute
]

# Also accept these keywords in the location field
SP_METRO_KEYWORDS = [
    "são paulo", "sao paulo", "sp,", ", sp",
    "remoto", "home office", "brasil", "brazil",
    "teletrabalho", "remoto (brasil)", "100% remoto"
]


def is_sp_metro_area(location: str) -> bool:
    """
    Check if a job location is in the São Paulo metropolitan area.
    Also accepts remote jobs.
    
    Returns True if the job should be KEPT.
    """
    loc = location.lower().strip()
    
    # Accept if any SP metro city or keyword is found
    for city in SP_METRO_CITIES:
        if city in loc:
            return True
    
    for keyword in SP_METRO_KEYWORDS:
        if keyword in loc:
            return True
    
    return False


# ----- RECENCY FILTER -----
MAX_DAYS_OLD = 7

# ----- RESULTS SETTINGS -----
RESULTS_PER_QUERY = 25
MIN_MATCH_SCORE = 0
