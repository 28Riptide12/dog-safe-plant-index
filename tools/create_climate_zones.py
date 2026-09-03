#!/usr/bin/env python3
"""
UK postcode areas mapped to RHS hardiness zones.
Based on UK Met Office climate zones and RHS plant hardiness classification.
Zones: H1a/H1b (frost-tender), H2 (frost-hardy), H3-H7 (hardy, increasingly cold-tolerant).
"""
import json
from pathlib import Path

UK_POSTCODE_ZONES = {
    # Southern England (H3-H4, milder)
    "BN": "H3-H4",  # Brighton and Hove
    "BR": "H3-H4",  # Bromley
    "CB": "H3-H4",  # Cambridge
    "CM": "H3-H4",  # Chelmsford
    "CO": "H3-H4",  # Colchester
    "CR": "H3-H4",  # Croydon
    "CT": "H3-H4",  # Canterbury
    "DA": "H3-H4",  # Dartford
    "EH": "H3-H4",  # East Ham
    "EN": "H3-H4",  # Enfield
    "GU": "H3-H4",  # Guildford
    "HA": "H3-H4",  # Harrow
    "HP": "H3-H4",  # Hemel Hempstead
    "IG": "H3-H4",  # Ilford
    "KT": "H3-H4",  # Kingston upon Thames
    "ME": "H3-H4",  # Medway
    "MK": "H3-H4",  # Milton Keynes
    "RH": "H3-H4",  # Redhill
    "RM": "H3-H4",  # Romford
    "RG": "H3-H4",  # Reading
    "SE": "H3-H4",  # London South East
    "SM": "H3-H4",  # Sutton
    "SN": "H3-H4",  # Swindon
    "SS": "H3-H4",  # Southend-on-Sea
    "SW": "H3-H4",  # London South West
    "TN": "H3-H4",  # Tunbridge Wells
    "TW": "H3-H4",  # Twickenham
    "UB": "H3-H4",  # Uxbridge
    "W": "H3-H4",   # London West
    "WC": "H3-H4",  # London West Central
    "WD": "H3-H4",  # Watford
    
    # Central/South Midlands (H4, moderate)
    "B": "H4",      # Birmingham
    "BH": "H4",     # Bournemouth
    "CV": "H4",     # Coventry
    "DE": "H4",     # Derby
    "DY": "H4",     # Dudley
    "E": "H4",      # London East
    "EC": "H4",     # London East Central
    "GL": "H4",     # Gloucester
    "GW": "H4",     # Gwent
    "HR": "H4",     # Hereford
    "LE": "H4",     # Leicester
    "N": "H4",      # London North
    "NC": "H4",     # London North Central
    "NE": "H4",     # London North East
    "NN": "H4",     # Northampton
    "NW": "H4",     # London North West
    "OX": "H4",     # Oxford
    "PO": "H4",     # Portsmouth
    "SL": "H4",     # Slough
    "SO": "H4",     # Southampton
    "SP": "H4",     # Salisbury
    "ST": "H4",     # Stoke-on-Trent
    "SY": "H4",     # Shrewsbury
    "TA": "H4",     # Taunton
    "WA": "H4",     # Warrington
    "WF": "H4",     # Wakefield
    "WR": "H4",     # Worcester
    "WS": "H4",     # Walsall
    "WV": "H4",     # Wolverhampton
    
    # North Midlands/South Wales (H4-H5)
    "CF": "H4-H5",  # Cardiff
    "CW": "H4-H5",  # Crewe
    "EX": "H4-H5",  # Exeter
    "LD": "H4-H5",  # Llandrindod Wells
    "NP": "H4-H5",  # Newport
    "PE": "H4-H5",  # Peterborough
    "SA": "H4-H5",  # Swansea
    "TQ": "H4-H5",  # Torquay
    "TR": "H4-H5",  # Truro
    "ZE": "H4-H5",  # Shetland
    
    # North West England (H5, colder)
    "BL": "H5",     # Bolton
    "CA": "H5",     # Carlisle
    "CH": "H5",     # Chester
    "CL": "H5",     # Clacton
    "EC": "H5",     # East Coast
    "FY": "H5",     # Fylde
    "L": "H5",      # Liverpool
    "LA": "H5",     # Lancaster
    "M": "H5",      # Manchester
    "OL": "H5",     # Oldham
    "PR": "H5",     # Preston
    "SK": "H5",     # Stockport
    "WN": "H5",     # Wigan
    
    # North East England (H5-H6, cold)
    "BD": "H5-H6",  # Bradford
    "DH": "H5-H6",  # Durham
    "HD": "H5-H6",  # Hebden Bridge
    "HG": "H5-H6",  # Harrogate
    "HL": "H5-H6",  # Hull
    "HX": "H5-H6",  # Halifax
    "LN": "H5-H6",  # Lincoln
    "NE": "H5-H6",  # Newcastle
    "NG": "H5-H6",  # Nottingham
    "OL": "H5-H6",  # Oldham
    "S": "H5-H6",   # Sheffield
    "SR": "H5-H6",  # Sunderland
    "YO": "H5-H6",  # York
    
    # Scotland (H6-H7, very cold)
    "AB": "H6-H7",  # Aberdeen
    "DD": "H6-H7",  # Dundee
    "DG": "H6-H7",  # Dumfries
    "EH": "H6-H7",  # Edinburgh
    "FK": "H6-H7",  # Falkirk
    "G": "H6-H7",   # Glasgow
    "KA": "H6-H7",  # Ayrshire
    "KW": "H6-H7",  # Kirkwall
    "KY": "H6-H7",  # Kirkcaldy
    "ML": "H6-H7",  # Motherwell
    "PA": "H6-H7",  # Paisley
    "PH": "H6-H7",  # Perth
    "TD": "H6-H7",  # Tweeddale
    "ZE": "H6-H7",  # Shetland/Orkney
    
    # Wales (H5-H6)
    "CH": "H5-H6",  # Ceredigion
    "LL": "H5-H6",  # Llandudno
    "NP": "H5-H6",  # Newport
    "LD": "H5-H6",  # Llandrindod
    "SA": "H5-H6",  # Swansea
    
    # Northern Ireland (H5-H6)
    "BT": "H5-H6",  # Belfast area
}

REPO_ROOT = Path(__file__).parent.parent
CLIMATE_DATA_FILE = REPO_ROOT / "database" / "climate_zones.json"

def create_climate_mapping():
    """Create UK postcode to hardiness zone mapping."""
    data = {
        "version": "1.0",
        "system": "uk_rhs_hardiness",
        "description": "UK postcode areas mapped to RHS hardiness zones (H1a-H7)",
        "hardiness_zones": {
            "H1a": {"label": "Half-hardy annuals", "min_temp_c": 15, "description": "Frost-tender, grow as annuals"},
            "H1b": {"label": "Half-hardy perennials", "min_temp_c": 10, "description": "Frost-tender but hardy in mild areas"},
            "H2": {"label": "Frost-hardy", "min_temp_c": 5, "description": "Survives -5 to +5°C"},
            "H3": {"label": "Hardy", "min_temp_c": 0, "description": "Survives 0 to -5°C"},
            "H4": {"label": "Hardy", "min_temp_c": -5, "description": "Survives -5 to -10°C"},
            "H5": {"label": "Hardy", "min_temp_c": -10, "description": "Survives -10 to -15°C"},
            "H6": {"label": "Hardy", "min_temp_c": -15, "description": "Survives -15 to -20°C"},
            "H7": {"label": "Very hardy", "min_temp_c": -20, "description": "Survives below -20°C"},
        },
        "postcode_map": UK_POSTCODE_ZONES,
    }
    
    with open(CLIMATE_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return {
        "file": str(CLIMATE_DATA_FILE),
        "postcodes": len(UK_POSTCODE_ZONES),
    }

if __name__ == "__main__":
    result = create_climate_mapping()
    print(f"Created climate zone mapping with {result['postcodes']} postcode areas")
    print(f"File: {result['file']}")
