"""ZIP code de Texas -> condado, acotado a los condados que alguna MGA bloquea.

Diana 2026-08-10 (AMWINS): *"es muy importante revisar en que condado se
encuentra mediante el zip code del physical ya que este programa seria
inelegible para los siguientes condados: Brazoria, Fort Bend, Galveston,
Harris, Montgomery, Hidalgo, Starr, Cameron y Beaumont"*.

Alcance deliberado: esto NO es un mapa de los 254 condados de Texas, solo de
los que hoy bloquean un programa. Un ZIP que no este aca devuelve None y el
rule engine emite un AVISO para revisar a mano — nunca un bloqueo silencioso.
Preferimos dejar pasar un riesgo que rechazarlo por un dato que no tenemos.

OJO — Beaumont es CIUDAD (condado Jefferson), no condado. Se bloquean los ZIP
de la ciudad de Beaumont, que es la lectura literal de lo que pidio Diana;
bloquear Jefferson entero (Port Arthur, Nederland, Groves, Port Neches) seria
mas amplio que lo pedido. Pendiente de confirmar con ella.
"""
from __future__ import annotations

from typing import Optional

# Rangos contiguos (inicio, fin, condado) — ambos extremos incluidos.
_RANGES = [
    # --- Harris (Houston y area metro) ---
    (77002, 77099, "Harris"),
    (77201, 77299, "Harris"),        # apartados postales de Houston
    (77502, 77507, "Harris"),        # Pasadena
    (77520, 77523, "Harris"),        # Baytown
    (77530, 77547, "Harris"),
    (77571, 77572, "Harris"),        # La Porte
    (77586, 77587, "Harris"),        # Seabrook / South Houston
    # --- Montgomery (Conroe, The Woodlands) ---
    (77301, 77306, "Montgomery"),
    (77380, 77387, "Montgomery"),
    # --- Galveston ---
    (77550, 77555, "Galveston"),     # isla de Galveston
    (77590, 77592, "Galveston"),     # Texas City
    # --- Hidalgo (McAllen, Edinburg) ---
    (78501, 78505, "Hidalgo"),
    (78541, 78543, "Hidalgo"),
    # --- Cameron (Brownsville, Harlingen) ---
    (78520, 78523, "Cameron"),
    (78550, 78553, "Cameron"),
    # --- Jefferson / ciudad de Beaumont ---
    (77701, 77713, "Beaumont"),
]

# ZIPs sueltos que no caen en ningun rango contiguo.
_SINGLES = {
    # --- Harris ---
    77336: "Harris", 77338: "Harris", 77339: "Harris", 77345: "Harris",
    77346: "Harris", 77347: "Harris", 77373: "Harris", 77375: "Harris",
    77377: "Harris", 77379: "Harris", 77383: "Harris", 77388: "Harris",
    77389: "Harris", 77396: "Harris", 77401: "Harris", 77402: "Harris",
    77410: "Harris", 77429: "Harris", 77433: "Harris", 77447: "Harris",
    77449: "Harris", 77450: "Harris", 77491: "Harris", 77492: "Harris",
    77493: "Harris", 77494: "Harris", 77562: "Harris", 77598: "Harris",
    # --- Fort Bend ---
    77406: "Fort Bend", 77407: "Fort Bend", 77417: "Fort Bend",
    77441: "Fort Bend", 77444: "Fort Bend", 77451: "Fort Bend",
    77459: "Fort Bend", 77461: "Fort Bend", 77464: "Fort Bend",
    77469: "Fort Bend", 77471: "Fort Bend", 77476: "Fort Bend",
    77477: "Fort Bend", 77478: "Fort Bend", 77479: "Fort Bend",
    77481: "Fort Bend", 77485: "Fort Bend", 77487: "Fort Bend",
    77489: "Fort Bend", 77496: "Fort Bend", 77497: "Fort Bend",
    77498: "Fort Bend", 77545: "Fort Bend",
    # --- Brazoria ---
    77422: "Brazoria", 77480: "Brazoria", 77486: "Brazoria",
    77511: "Brazoria", 77512: "Brazoria", 77515: "Brazoria",
    77516: "Brazoria", 77531: "Brazoria", 77534: "Brazoria",
    77541: "Brazoria", 77542: "Brazoria", 77566: "Brazoria",
    77577: "Brazoria", 77578: "Brazoria", 77581: "Brazoria",
    77582: "Brazoria", 77584: "Brazoria", 77588: "Brazoria",
    # --- Galveston ---
    77510: "Galveston", 77517: "Galveston", 77518: "Galveston",
    77539: "Galveston", 77546: "Galveston", 77549: "Galveston",
    77563: "Galveston", 77565: "Galveston", 77568: "Galveston",
    77573: "Galveston", 77617: "Galveston", 77623: "Galveston",
    77650: "Galveston",
    # --- Montgomery ---
    77316: "Montgomery", 77318: "Montgomery", 77333: "Montgomery",
    77354: "Montgomery", 77355: "Montgomery", 77356: "Montgomery",
    77357: "Montgomery", 77362: "Montgomery", 77365: "Montgomery",
    77372: "Montgomery", 77378: "Montgomery", 77393: "Montgomery",
    # --- Hidalgo ---
    78516: "Hidalgo", 78537: "Hidalgo", 78538: "Hidalgo", 78539: "Hidalgo",
    78557: "Hidalgo", 78558: "Hidalgo", 78560: "Hidalgo", 78562: "Hidalgo",
    78563: "Hidalgo", 78565: "Hidalgo", 78570: "Hidalgo", 78572: "Hidalgo",
    78573: "Hidalgo", 78574: "Hidalgo", 78576: "Hidalgo", 78577: "Hidalgo",
    78579: "Hidalgo", 78589: "Hidalgo", 78595: "Hidalgo", 78596: "Hidalgo",
    78599: "Hidalgo",
    # --- Starr ---
    78536: "Starr", 78545: "Starr", 78547: "Starr", 78548: "Starr",
    78582: "Starr", 78584: "Starr", 78585: "Starr", 78588: "Starr",
    78591: "Starr",
    # --- Cameron ---
    78526: "Cameron", 78535: "Cameron", 78559: "Cameron", 78566: "Cameron",
    78567: "Cameron", 78568: "Cameron", 78575: "Cameron", 78578: "Cameron",
    78583: "Cameron", 78586: "Cameron", 78593: "Cameron", 78597: "Cameron",
    78598: "Cameron",
    # --- Beaumont (ciudad) ---
    77720: "Beaumont", 77725: "Beaumont", 77726: "Beaumont",
}


# Todos los condados bloqueados viven en estos prefijos ZIP3: area metro de
# Houston (770-775), Beaumont (777) y el Valle del Rio Grande (785). Un ZIP de
# Dallas, Austin, San Antonio o El Paso no puede caer en ninguno, asi que se
# resuelve sin pedir revision manual — si no, cada cotizacion de Dallas
# arrastraria un aviso inutil y los avisos que importan se perderian.
_RISK_PREFIXES = {"770", "771", "772", "773", "774", "775", "777", "785"}

OUTSIDE_RISK_AREA = "(fuera del area de los condados bloqueados)"


def county_for_zip(zip_code) -> Optional[str]:
    """Condado del ZIP.

    Devuelve el nombre del condado si esta mapeado; `OUTSIDE_RISK_AREA` si el
    ZIP esta demostrablemente lejos de todos los condados bloqueados; o None si
    cae en la zona de riesgo pero no lo tenemos mapeado (-> revision manual).
    """
    if zip_code is None:
        return None
    digits = "".join(c for c in str(zip_code) if c.isdigit())[:5]
    if len(digits) != 5:
        return None
    z = int(digits)
    if z in _SINGLES:
        return _SINGLES[z]
    for lo, hi, county in _RANGES:
        if lo <= z <= hi:
            return county
    if digits[:3] not in _RISK_PREFIXES:
        return OUTSIDE_RISK_AREA
    return None
