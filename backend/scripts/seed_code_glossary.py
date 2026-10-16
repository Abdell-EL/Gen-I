"""Seed the code glossary tables (closure_codes, network_segments, zones, regions,
activite_codes) from the 2026-10 KB audit of the real Excel workbook.

Every entry's `source_notes` names the sheet(s) or screenshot(s) it was read from
(see excel-sources/SHEET_MAP.md and excel-sources/CODE_GLOSSARY.md for the full
audit). `confidence` is "confirmed_by_text" only when an explicit definition was
found in a source; otherwise it is "context_only" -- the code is real and the
usage is real, but no plain-language definition for it has been found yet, and
`meaning` is left as None rather than guessed.

Run inside the api container: docker exec lab_api python scripts/seed_code_glossary.py
Idempotent: upserts by the natural key (code, or code+perimeter for activite_codes).
"""

from __future__ import annotations

from app.database import SessionLocal
from app.models import ClosureCode, NetworkSegment, Zone, Region, ActiviteCode


CLOSURE_CODES = [
    dict(
        code="DMS", family="cloture",
        meaning="Clôture indiquant une intervention/un raccordement réussi "
                "(\"Mise en service\"). Pour une TAC/FTH : la TAC a permis de "
                "raccorder le client.",
        confidence="confirmed_by_text",
        source_notes="Setting PRODCUIVRE ABRFTCMC (valeurs réelles) ; "
                      "Facturation FTTH capture \"Synthèse Clôture TAC/FTH\" ; "
                      "Test de Ligne & Joker capture (menu déroulant \"DMS - Mise en service\").",
    ),
    dict(
        code="TKO", family="cloture",
        meaning="Code \"réussite\" qui permet la rémunération fournisseur, utilisé "
                "quand la TAC/FTH a été réalisée mais n'a pas permis de raccorder "
                "le client (synchro non confirmée).",
        confidence="confirmed_by_text",
        source_notes="Facturation FTTH capture \"Synthèse Clôture TAC/FTH\" ; "
                      "F04_p03 capture (\"Clôture en réussite\" / TKO synchro nok).",
    ),
    dict(
        code="ANN", family="cloture",
        meaning="Annulation. Pour une TAC/FTH : la TAC n'était pas nécessaire "
                "(erreur de diagnostic initial). Pour F04/P03 : annulation client.",
        confidence="confirmed_by_text",
        source_notes="Facturation FTTH capture \"Synthèse Clôture TAC/FTH\" ; F04_p03 capture.",
    ),
    dict(
        code="RMC", family="cloture",
        meaning=None,
        confidence="context_only",
        source_notes="Setting PRODCUIVRE ABRFTCMC (valeur réelle, utilisée pour les cas "
                      "\"Gem interdit\" ex. MSH/EPR) ; Test de Ligne & Joker capture "
                      "(\"Code de relève\"). Aucune définition textuelle explicite trouvée.",
    ),
    dict(
        code="GEM AB", family="GEM",
        meaning="Le client était absent (cause de l'échec).",
        confidence="confirmed_by_text",
        source_notes="Facturation FTTH capture \"Synthèse Clôture TAC/FTH\" (TAC GEM AB) ; "
                      "GEM-CUIVRE-010, FTTH-GEM-ELIG-009.",
    ),
    dict(
        code="GEM RF", family="GEM",
        meaning="Le technicien n'a pas pu honorer le TRDV.",
        confidence="confirmed_by_text",
        source_notes="Facturation FTTH capture \"Synthèse Clôture TAC/FTH\" (TAC GEM RF) ; "
                      "GEM-CUIVRE-010.",
    ),
    dict(
        code="GEM TC", family="GEM",
        meaning=None,
        confidence="context_only",
        source_notes="Setting PRODCUIVRE ABRFTCMC / Setting Fibre abrftcmc (type d'échec, "
                      "valeur réelle). Aucune définition textuelle explicite trouvée.",
    ),
    dict(
        code="GEM TVC", family="GEM",
        meaning=None,
        confidence="context_only",
        source_notes="Setting PRODCUIVRE ABRFTCMC (type d'échec, valeur réelle). "
                      "Aucune définition textuelle explicite trouvée.",
    ),
    dict(
        code="GEM BL", family="GEM",
        meaning=None,
        confidence="context_only",
        source_notes="Expertise & Fiabilisation capture (\"il fera un GEM BL s'il peut "
                      "corriger le défaut en autonomie\"). Contexte seulement.",
    ),
    dict(
        code="ORT", family="cloture",
        meaning=None,
        confidence="context_only",
        source_notes="F04_p03 capture (\"ORT ou REO IS\" pour \"Pb insalubrité PM\") ; "
                      "ACCES-SERVICE-012, SAV-CLOT-016. Contexte seulement.",
    ),
    dict(
        code="REO", family="cloture",
        meaning=None,
        confidence="context_only",
        source_notes="Actualité FDE capture (\"# SAV REO AI\", \"#PROD REO AI\") ; "
                      "Expertise & Fiabilisation capture (\"REO RR/VA\") ; ACCES-SERVICE-012. "
                      "Contexte seulement (plusieurs suffixes AI/IS/RR-VA, pas de définition unique).",
    ),
    dict(
        code="ETU", family="cloture",
        meaning=None,
        confidence="context_only",
        source_notes="F04_p03 capture (code pour \"Pb porte gauche\"). Contexte seulement.",
    ),
    dict(
        code="PBCF3", family="cloture",
        meaning="Code de clôture pour \"Absence signal box\" ; à utiliser aussi si le "
                "client n'a pas branché sa box, avec explication dans le commentaire de clôture.",
        confidence="confirmed_by_text",
        source_notes="F04_p03 capture (annotation explicite sous la colonne F04).",
    ),
    dict(
        code="PAD", family="cloture",
        meaning=None,
        confidence="context_only",
        source_notes="F04_p03 capture (code pour \"Problème d'adresse\", commentaire "
                      "\"Rappel spécialiste\") ; Test de Ligne & Joker capture (\"Code de relève\"). "
                      "Contexte seulement.",
    ),
    dict(
        code="DOP", family="releve",
        meaning="Défaut du plot opérateur.",
        confidence="confirmed_by_text",
        source_notes="Test de Ligne & Joker capture (\"Test de Ligne sur une clôture en DOP\").",
    ),
    dict(
        code="DIP", family="releve", meaning=None, confidence="context_only",
        source_notes="Test de Ligne & Joker capture (table \"Code de relève\", mesure obligatoire OUI).",
    ),
    dict(
        code="DEF", family="releve", meaning=None, confidence="context_only",
        source_notes="Test de Ligne & Joker capture (table \"Code de relève\") ; "
                      "Actualité FDE capture (\"DEF DMS\"). Contexte seulement.",
    ),
    dict(
        code="PDC", family="releve", meaning=None, confidence="context_only",
        source_notes="Test de Ligne & Joker capture (table \"Code de relève\", mesure obligatoire OUI).",
    ),
    dict(
        code="PRO", family="releve", meaning=None, confidence="context_only",
        source_notes="Test de Ligne & Joker capture (table \"Code de relève\", mesure obligatoire OUI).",
    ),
    dict(
        code="ICI", family="releve", meaning=None, confidence="context_only",
        source_notes="Test de Ligne & Joker capture (table \"Code de relève\", mesure obligatoire OUI).",
    ),
    dict(
        code="FCDx", family="prestation",
        meaning="Code prestation pour une intervention de fiabilisation, "
                "utilisé si la ligne est LBE.",
        confidence="confirmed_by_text",
        source_notes="Expertise & Fiabilisation capture (\"Levier Wholesale - sortie du "
                      "processus de fiabilisation\").",
    ),
    dict(
        code="SAVCx", family="prestation",
        meaning="Code prestation pour une intervention d'incident, "
                "utilisé si la ligne est non-LBE.",
        confidence="confirmed_by_text",
        source_notes="Expertise & Fiabilisation capture (\"Levier Wholesale - sortie du "
                      "processus de fiabilisation\").",
    ),
]

NETWORK_SEGMENTS = [
    dict(code="PAU", family="PAU", meaning_label="Autocommutateur",
         source="segment de tête, libellé \"Autocommutateur\" dans le diagramme"),
    dict(code="PRE", family="PRE", meaning_label="Répartiteur",
         source="libellé \"Répartiteur\" dans le diagramme"),
    dict(code="PLI", family="PLI", meaning_label=None, source="segment du diagramme"),
    dict(code="PBR", family="PBR", meaning_label=None, source="segment du diagramme"),
    dict(code="PIT", family="PIT", meaning_label=None, source="segment du diagramme (domicile client)"),
    dict(code="D1", family="PLI", meaning_label="Transport", source="flèche \"Transport\" entre PRE et PLI"),
    dict(code="D2", family="PBR", meaning_label="Distribution", source="flèche \"Distribution\" entre PLI et PBR"),
    dict(code="D3", family="PIT", meaning_label="Entrée de Poste", source="flèche \"Entrée de Poste\" entre PBR et PIT"),
    dict(code="AU", family="PAU", meaning_label=None, source="sous-code \"DIVERS\" sous PAU"),
    dict(code="RE", family="PRE", meaning_label=None, source="sous-code (DIVERS, MUTNE, MUTDSL) sous PRE"),
    dict(code="TR", family="PLI", meaning_label=None, source="sous-code (DIVERS, MUTHS, MUTTR, SAT) sous PLI"),
    dict(code="SR", family="PLI", meaning_label=None, source="sous-code (DIVERS, MUTHS, PM) sous PLI"),
    dict(code="DI", family="PLI", meaning_label=None, source="sous-code (DIVERS, MUTDI, SAT) sous PLI"),
    dict(code="PM", family="PLI", meaning_label=None, source="repère PM (vert, code lieu FTTH) sous SR"),
    dict(code="PC", family="PBR", meaning_label=None, source="sous-code \"DIVERS\" sous PBR"),
    dict(code="PB", family="PBR", meaning_label=None, source="repère PB (vert, code lieu FTTH) sous PC"),
    dict(code="BR", family="PBR", meaning_label=None,
         source="sous-code (BRABO/DESCAB si public, desserte câblée si privé) sous PBR"),
    dict(code="IN", family="PIT", meaning_label="Desserte Interne",
         source="sous-code (DTI, PTO, PTIO, ONT) sous PIT"),
    dict(code="TE", family="PIT", meaning_label=None,
         source="sous-code (RTEUR si Retail, EQCLI si Wholesale) sous PIT"),
    dict(code="DTI", family="PIT", meaning_label=None, source="équipement sous IN"),
    dict(code="PTO", family="PIT", meaning_label=None, source="équipement sous IN"),
    dict(code="PTIO", family="PIT", meaning_label=None, source="équipement sous IN"),
    dict(code="ONT", family="PIT", meaning_label=None, source="équipement sous IN"),
    dict(code="RTEUR", family="PIT", meaning_label=None, source="équipement sous TE (Retail)"),
    dict(code="EQCLI", family="PIT", meaning_label=None, source="équipement sous TE (Wholesale)"),
]

ZONES = [
    dict(code="IDFZ1", label="DOIDF Zone 1 (Cuivre)"),
    dict(code="RMZ3", label="DORM Zone 3 (LOT 2)"),
    dict(code="RMZ1", label="DORM Zone 1 (Mixte, LOT 1 + LOT 2)"),
    dict(code="GSOZ5", label="DOGSO Zone 5 (LOT 1, FTH et Cuivre)"),
    dict(code="GSOZ1", label="DOGSO Zone 1 (LOT 1, FTH et Cuivre)"),
    dict(code="GSEZ6", label="DOGSE Zone 6 (DEBORDEMENT, Cuivre)"),
    dict(code="GOZ4", label="DOGO Zone 4 (DEBORDEMENT, Cuivre)"),
    dict(code="GOZ3", label="DOGO Zone 3 (LOT 1, FTH)"),
    dict(code="GOZ2", label="DOGO Zone 2 (LOT 3)"),
    dict(code="GOZ1", label="DOGO Zone 1 (LOT 2 Cuivre, et DEBORDEMENT)"),
    dict(code="LPC", label="DO SUD OUEST - Zone 1 LPC (Cuivre)"),
    dict(code="AQU", label="DO SUD OUEST - Zone 4 AQ (Cuivre)"),
]

REGIONS = [
    dict(code="IDF", label="Île-de-France (tickets GEM U2/U6)"),
    dict(code="BZH", label="Bretagne (tickets GEM Q2)"),
    dict(code="DOM TOM", label="DOM TOM"),
    dict(code="LANGUEDOC-ROUSSILLON", label="Languedoc-Roussillon (tickets GEM K2/T1)"),
    dict(code="NORMANDIE", label="Normandie (tickets GEM R0)"),
    dict(code="SUD-OUEST", label="Sud-Ouest (tickets GEM B2/P0)"),
    dict(code="REUNION", label="Réunion (lot \"FO REU\", maintenance fibre et travaux réseaux)"),
    dict(code="SUD-EST", label=None,
         source_extra="Cité dans RDV-REINJECTION-CONSIGNES-008 comme une des 5 régions "
                       "(IDF, Normandie, Sud Ouest, Sud Est, BZH) ; non vu directement dans "
                       "une capture de ce classeur -- à confirmer."),
]

# EXC appears ONLY in the FTTH GEM matrix (Maintenance, Hors BtB). IDV appears in
# BOTH the Cuivre activité list (GEM-CUIVRE-010, Production) and the FTTH GEM
# matrix (Production, BtB) -- same letters, two different perimeters. This is
# exactly the distinction the EXC/IDV pilot bug needed and didn't have.
ACTIVITE_CODES_CUIVRE = [
    "R02", "R03", "R04", "R10", "MSH", "EPR", "IHD", "LMD", "LMV", "LML", "LMC",
    "MIT", "IDV", "TPO", "RTT", "PRE", "PLI", "PBR", "PIT", "PFC-PFE-PMS", "ESC",
]
ACTIVITE_CODE_CUIVRE_DET_MT = "DET MT"

ACTIVITE_CODES_FTTH_PRODUCTION = {
    "R02": "BtB", "R03": "BtB", "R04": "BtB", "R10": "BtB",
    "LML": "BtB et Hors BtB", "MIT": "BtB", "MSH": "GEM Interdit",
    "EPR": "BtB", "IDV": "BtB",
}
ACTIVITE_CODES_FTTH_MAINTENANCE = {
    "PRE/PLI": "BtB", "PBR": "BtB", "PIT": "BtB", "PMS PFC": "BtB",
    "PFE PFX": "Hors BtB", "EMA": "BtB et Hors BtB", "ADI": "BtB",
    "PFO/PCC": "BtB", "PPC CPC": "BtB", "PFG PCG": None,
    "EXC": "Hors BtB", "ESC": "BtB",
}


def upsert(session, model, lookup: dict, values: dict):
    row = session.query(model).filter_by(**lookup).one_or_none()
    if row is None:
        row = model(**lookup)
        session.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    return row


def main() -> None:
    session = SessionLocal()
    try:
        for entry in CLOSURE_CODES:
            upsert(
                session, ClosureCode, {"code": entry["code"]},
                {
                    "label": None,
                    "meaning": entry["meaning"],
                    "family": entry["family"],
                    "confidence": entry["confidence"],
                    "source_notes": entry["source_notes"],
                },
            )

        for entry in NETWORK_SEGMENTS:
            upsert(
                session, NetworkSegment, {"code": entry["code"]},
                {
                    "label": entry["meaning_label"],
                    "family": entry["family"],
                    "confidence": "confirmed_by_text" if entry["meaning_label"] else "context_only",
                    "source_notes": f"Aide à la clôture SAV, diagramme réseau -- {entry['source']}.",
                },
            )

        for entry in ZONES:
            upsert(
                session, Zone, {"code": entry["code"]},
                {
                    "label": entry["label"],
                    "perimeter": None,
                    "confidence": "confirmed_by_text",
                    "source_notes": "Methodologie de clôture, capture liste de lots LC0706xx "
                                     "(filtre Gesica) -- recoupe les zones de LOT-CHANTIER-021.",
                },
            )

        for entry in REGIONS:
            upsert(
                session, Region, {"code": entry["code"]},
                {
                    "label": entry["label"],
                    "confidence": "confirmed_by_text" if entry.get("label") else "context_only",
                    "source_notes": entry.get(
                        "source_extra",
                        "Traitement des RPR, capture liste de tickets GEM SO'Desk par région.",
                    ),
                },
            )

        for code in ACTIVITE_CODES_CUIVRE:
            upsert(
                session, ActiviteCode, {"code": code, "perimeter": "Cuivre"},
                {
                    "label": None,
                    "family": None,
                    "confidence": "confirmed_by_text",
                    "source_notes": "Setting PRODCUIVRE ABRFTCMC (22 activités réelles, "
                                     "GEM-CUIVRE-010, audité fidèle le 2026-10-14).",
                },
            )
        upsert(
            session, ActiviteCode, {"code": ACTIVITE_CODE_CUIVRE_DET_MT, "perimeter": "Cuivre"},
            {
                "label": "Dérangement Étoile (DET) / traitement différé (MNT)",
                "family": "DET/MNT",
                "confidence": "confirmed_by_text",
                "source_notes": "Setting PRODCUIVRE ABRFTCMC (22e activité) ; "
                                 "Gestar capture \"Mode opératoire\" définit DET = "
                                 "\"Ex Dérangement Étoile\" (P1/P2/P3, traitement immédiat) "
                                 "et MNT = traitement différé (P4).",
            },
        )

        for code, family in ACTIVITE_CODES_FTTH_PRODUCTION.items():
            upsert(
                session, ActiviteCode, {"code": code, "perimeter": "FTTH"},
                {
                    "label": None,
                    "family": f"Production, {family}" if family else "Production",
                    "confidence": "confirmed_by_text",
                    "source_notes": "Expertise & Fiabilisation capture (matrice d'éligibilité GEM "
                                     "FTTH, colonne Production). Confirme qu'IDV (FTTH, Production, "
                                     "BtB) est distinct d'IDV (Cuivre, activité GEM-CUIVRE-010).",
                },
            )
        for code, family in ACTIVITE_CODES_FTTH_MAINTENANCE.items():
            upsert(
                session, ActiviteCode, {"code": code, "perimeter": "FTTH"},
                {
                    "label": None,
                    "family": f"Maintenance, {family}" if family else "Maintenance",
                    "confidence": "confirmed_by_text",
                    "source_notes": "Expertise & Fiabilisation capture (matrice d'éligibilité GEM "
                                     "FTTH, colonne Maintenance). EXC = Maintenance, Hors BtB -- "
                                     "distinct d'IDV (Production, BtB), la confusion du bug pilote.",
                },
            )

        session.commit()

        print("Seeded:")
        print(f"  closure_codes:    {session.query(ClosureCode).count()}")
        print(f"  network_segments: {session.query(NetworkSegment).count()}")
        print(f"  zones:            {session.query(Zone).count()}")
        print(f"  regions:          {session.query(Region).count()}")
        print(f"  activite_codes:   {session.query(ActiviteCode).count()}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
