"""Patch the confirmed-wrong chunks in chunks.json for SBL-TRAIT-029 (25
chunks) and F04-P03-003 (8 chunks), found during the 2026-10-15 proofreading
pass (see PROGRESS.md) and now that the replacement decision tables
(`SBL - Cas rencontré vers action GESICA`, `F04/P03 - Codes de clôture et
messages client`) exist and are verified against the real screenshots.

F04-P03-003: single find-replace, PBCF5 -> PBCF3 (8 chunks, no structural issue).

SBL-TRAIT-029: structural fix, not a typo fix. The generated article had the
threshold direction backwards for REO/VA: it believed REO/VA applied to the
"<threshold" tier (impossible repair) and PRO/OR to the ">threshold" tier
(repair done). The real table has no closure-code branch at all for
"<threshold" cases (ré-injection only) -- REO/VA and PRO/QR are BOTH
">threshold" outcomes, chosen by whether a provisional repair was made.
Each of the 25 chunks is corrected by hand below; a blind string-replace
can't fix this since it's not the same wrong substring everywhere.

Run: python3 scripts/fix_sbl_f04_chunks.py
(host or container, just needs read/write access to data/processed/chunks.json)
"""
import json

CHUNKS_PATH = "data/processed/chunks.json"

F04_REPLACEMENTS = {
    # external_chunk_id -> new text
    "F04-P03-003::0003": (
        "La feuille présente des cas de clôture ou de traitement liés aux interventions fibre : "
        "rendez-vous manqué fournisseur, problème de serrure PM, insalubrité PM, porte gauche "
        "ETU, réussite TKO, casse voisin, problème d’adresse, absence signal box et annulation "
        "client. Chaque cas doit être associé au code ou motif de clôture correspondant avant "
        "communication client. Pour l’absence signal box, le code PBCF3 est également indiqué "
        "lorsque le client n’a pas branché sa box, avec une explication obligatoire dans le "
        "commentaire de clôture -- c’est le même code que pour la casse voisin, la capture "
        "précisant explicitement que ce code sert aux deux cas. Les messages client doivent être "
        "adaptés au parcours Orange ou Sosh lorsque la capture distingue les deux environnements. "
        "Plusieurs codes sont issus d’OCR sur capture et doivent être validés dans le référentiel "
        "métier officiel avant usage opérationnel définitif."
    ),
    "F04-P03-003::0004": (
        "Pour la feuille F04_p03, le conseiller doit identifier le cas opérationnel fibre, "
        "sélectionner le code ou motif de clôture correspondant, puis appliquer le message client "
        "associé. Les cas visibles couvrent notamment le RDV manqué fournisseur, les problèmes PM, "
        "la réussite de mise en service, la casse voisin, le problème d’adresse, l’absence signal "
        "box et l’annulation client. Les codes extraits depuis la capture doivent être confirmés "
        "dans le référentiel métier, sauf la règle clairement visible indiquant que PBCF3 peut "
        "aussi être utilisé si le client n’a pas branché sa box, avec explication dans le "
        "commentaire de clôture (le même code que pour la casse voisin)."
    ),
    "F04-P03-003::0020": (
        "PM : Point de mutualisation. OT : Ordre de travail ou intervention à traiter. TKO : Cas "
        "de traitement lié à un test ou une intervention technique ; la signification exacte doit "
        "être confirmée dans le référentiel métier. DMS : Code ou statut visible dans la capture, "
        "associé à une synchronisation OK ; à valider. MES : Mise en service. PBCF3 : Code visible "
        "pour la casse voisin, également utilisé pour l’absence signal box si le client n’a pas "
        "branché sa box, avec explication dans le commentaire de clôture. ANN : Code visible pour "
        "annulation client. OCR : Reconnaissance optique de caractères utilisée pour extraire le "
        "texte depuis la capture Excel."
    ),
    "F04-P03-003::0028": (
        "Cas: Absence signal box\n"
        "Codes ou motifs visibles : PBCF3 ; le même code que pour la casse voisin, à utiliser "
        "aussi si le client n’a pas branché sa box avec explication dans le commentaire de "
        "clôture.\n"
        "Traitement attendu : Utiliser PBCF3 lorsqu’il y a absence de signal box. Si le client "
        "n’a pas branché sa box, utiliser également ce code et expliquer la situation dans le "
        "commentaire de clôture.\n"
        "Message client associé : Message Orange de type : installation de la ligne Fibre non "
        "réalisée ; une nouvelle intervention sera proposée le plus rapidement possible.\n"
        "Niveau de fiabilité : Règle visible dans la capture ; confirmée le 2026-10-15."
    ),
    "F04-P03-003::0034": "Si le cas est une absence signal box, alors le conseiller doit utiliser le code PBCF3.",
    "F04-P03-003::0035": (
        "Si le client n’a pas branché sa box, alors le conseiller peut également utiliser le code "
        "PBCF3 (le même que pour la casse voisin) et doit expliquer ce point dans le commentaire "
        "de clôture."
    ),
    "F04-P03-003::0040": (
        "Question: Quel code utiliser pour une absence signal box ?\n"
        "Réponse: Le code visible dans la capture est PBCF3, le même que pour la casse voisin. "
        "La capture précise également que ce code peut être utilisé si le client n’a pas branché "
        "sa box, à condition d’ajouter une explication dans le commentaire de clôture."
    ),
    "F04-P03-003::0041": (
        "Question: Que faire si le client n’a pas branché sa box ?\n"
        "Réponse: Utiliser PBCF3 selon la règle visible, puis documenter explicitement dans le "
        "commentaire de clôture que la box n’était pas branchée."
    ),
}

SBL_REPLACEMENTS = {
    "SBL-TRAIT-029::0002": (
        "Cet article formalise les règles de traitement SBL visibles dans la feuille Excel "
        "« Traitement SBL ». Il décrit les actions à appliquer dans GESICA selon le cas "
        "rencontré, notamment pour les défauts sur câble souterrain, câble aérien, câble "
        "multipaires, réfection d’épissure, RP et Transport HS. L’objectif est de transformer "
        "le tableau source en règles métier exploitables par le chatbot interne : pour les cas "
        "sous seuil (ou en zone directe pour le Transport HS), le traitement consiste à "
        "réinjecter le dossier sur site/SBL avec un type CLT et les causes BB et BL. Pour les "
        "cas au-dessus du seuil (ou hors zone directe), le traitement consiste à clôturer "
        "directement dans GESICA : en REO/VA si la réparation provisoire est impossible, ou en "
        "PRO/QR si elle a été réalisée."
    ),
    "SBL-TRAIT-029::0003": (
        "La feuille source contient principalement une image de tableau ; le texte a été extrait "
        "et restructuré en règles métier. Pour les cas sous seuil ou en zone directe, l’action "
        "unique est la ré-injection sur site/SBL en type CLT avec cause BB et BL -- il n’y a pas "
        "de branchement par code de clôture à ce niveau. Pour les cas au-dessus du seuil ou hors "
        "zone directe, la règle visible indique une clôture GESICA directe : en REO/VA si la "
        "réparation provisoire est impossible, ou en PRO/QR si elle est réalisée. Les seuils "
        "structurants sont 112 paires pour le câble souterrain, 56 paires pour le câble aérien ou "
        "le câble souterrain selon la ligne, 100 mètres pour le câble multipaires, 224 paires pour "
        "l’épissure et 56 paires pour le RP."
    ),
    "SBL-TRAIT-029::0005": (
        "Pour un traitement SBL, si le cas est sous seuil ou en zone directe, il faut réinjecter "
        "le dossier sur site/SBL en type CLT avec les causes BB et BL -- aucune clôture directe à "
        "ce niveau. Si le cas est au-dessus du seuil ou concerne un Transport HS sous pression "
        "hors zone directe, la règle visible indique une clôture GESICA directe : en REO/VA si la "
        "réparation provisoire est impossible, ou en PRO/QR si elle est réalisée. Les seuils à "
        "contrôler sont notamment 112 paires pour le câble souterrain, 56 paires pour le câble "
        "aérien ou RP, 100 mètres pour le câble multipaires et 224 paires pour l’épissure."
    ),
    "SBL-TRAIT-029::0015": "Quand utiliser PRO/QR dans GESICA ?",
    "SBL-TRAIT-029::0027": (
        "SBL : Traitement ou file de traitement mentionné dans la feuille source ; la "
        "signification exacte doit être confirmée par le référentiel métier. GESICA : Outil ou "
        "environnement dans lequel les actions de clôture, ré-injection ou mise à jour du dossier "
        "sont réalisées. GEMBeB : Colonne ou périmètre de clôture visible dans la capture ; la "
        "signification exacte doit être validée. Réaffecté-BL : Action ou statut de réaffectation "
        "vers BL visible dans le tableau source. CLT : Type de traitement à utiliser lors de la "
        "ré-injection sur site/SBL selon la source. Cause BB et BL : Causes à renseigner lors de "
        "la ré-injection sur site/SBL pour les cas concernés. REO/VA : Code de clôture GESICA à "
        "utiliser pour les cas au-dessus du seuil ou hors zone directe, lorsque la réparation "
        "provisoire est impossible. PRO/QR : Code de clôture GESICA à utiliser pour les cas "
        "au-dessus du seuil ou hors zone directe, lorsqu’une réparation provisoire est réalisée. "
        "RP : Libellé visible dans la règle de réfection d’épissure ; la signification exacte doit "
        "être confirmée. Transport HS : Cas de défaut transport hors service, distingué entre "
        "zone directe et sous pression hors zone directe."
    ),
    "SBL-TRAIT-029::0028": (
        "7.1 Logique de décision SBL\n"
        "La logique du tableau source repose sur une comparaison du cas rencontré avec un seuil "
        "métier. Les cas inférieurs au seuil, ou le Transport HS en zone directe, sont orientés "
        "vers une ré-injection sur site/SBL en type CLT avec les causes BB et BL, sans branchement "
        "par code de clôture. Les cas supérieurs au seuil, ou le Transport HS sous pression hors "
        "zone directe, sont orientés vers une clôture GESICA directe : en REO/VA si la réparation "
        "provisoire est impossible, ou en PRO/QR si elle est réalisée.\n"
        "7.2 Cas à réinjecter sur site/SBL\n"
        "Défaut sur câble souterrain inférieur à 112 paires.\n"
        "Défaut sur câble aérien inférieur à 56 paires.\n"
        "Remplacement de câble multipaires inférieur à 100 mètres.\n"
        "Réfection d’épissure inférieure à 224 paires ou RP inférieure à 56 paires.\n"
        "Défaut sur Transport HS en zone directe.\n"
        "Action attendue : Ré-injection sur site / SBL en type CLT avec cause BB et BL.\n"
        "7.3 Cas à clôturer directement en GESICA (REO/VA ou PRO/QR)\n"
        "Défaut sur câble souterrain supérieur à 112 paires.\n"
        "Défaut sur câble souterrain supérieur à 56 paires.\n"
        "Remplacement de câble multipaires supérieur à 100 mètres.\n"
        "Réfection d’épissure supérieure à 224 paires ou RP supérieure à 56 paires.\n"
        "Défaut sur Transport HS sous pression hors zone directe.\n"
        "Action attendue : Clôture GESICA en REO/VA si la réparation provisoire est impossible ; "
        "clôture GESICA en PRO/QR si la réparation provisoire est réalisée."
    ),
    "SBL-TRAIT-029::0030": (
        "Si le cas rencontré est : Défaut sur câble souterrain inférieur à 112 paires. alors il "
        "faut appliquer l’action suivante : Ré-injection sur site / SBL en type CLT avec cause BB "
        "et BL."
    ),
    "SBL-TRAIT-029::0031": (
        "Si le cas rencontré est : Défaut sur câble aérien inférieur à 56 paires. alors il faut "
        "appliquer l’action suivante : Ré-injection sur site / SBL en type CLT avec cause BB et BL."
    ),
    "SBL-TRAIT-029::0032": (
        "Si le cas rencontré est : Remplacement de câble multipaires inférieur à 100 mètres. "
        "alors il faut appliquer l’action suivante : Ré-injection sur site / SBL en type CLT avec "
        "cause BB et BL."
    ),
    "SBL-TRAIT-029::0033": (
        "Si le cas rencontré est : Réfection d’épissure inférieure à 224 paires ou RP inférieure "
        "à 56 paires. alors il faut appliquer l’action suivante : Ré-injection sur site / SBL en "
        "type CLT avec cause BB et BL."
    ),
    "SBL-TRAIT-029::0034": (
        "Si le cas rencontré est : Défaut sur Transport HS en zone directe. alors il faut "
        "appliquer l’action suivante : Ré-injection sur site / SBL en type CLT avec cause BB et BL."
    ),
    "SBL-TRAIT-029::0035": (
        "Si le cas rencontré est : Défaut sur câble souterrain supérieur à 112 paires. alors il "
        "faut appliquer l’action suivante : Clôture GESICA en REO/VA si la réparation provisoire "
        "est impossible ; clôture GESICA en PRO/QR si la réparation provisoire est réalisée."
    ),
    "SBL-TRAIT-029::0036": (
        "Si le cas rencontré est : Défaut sur câble souterrain supérieur à 56 paires (confirmé "
        "2026-10-15 contre la capture réelle). alors il faut appliquer l’action suivante : "
        "Clôture GESICA en REO/VA si la réparation provisoire est impossible ; clôture GESICA en "
        "PRO/QR si la réparation provisoire est réalisée."
    ),
    "SBL-TRAIT-029::0037": (
        "Si le cas rencontré est : Remplacement de câble multipaires supérieur à 100 mètres. "
        "alors il faut appliquer l’action suivante : Clôture GESICA en REO/VA si la réparation "
        "provisoire est impossible ; clôture GESICA en PRO/QR si la réparation provisoire est "
        "réalisée."
    ),
    "SBL-TRAIT-029::0038": (
        "Si le cas rencontré est : Réfection d’épissure supérieure à 224 paires ou RP supérieure "
        "à 56 paires. alors il faut appliquer l’action suivante : Clôture GESICA en REO/VA si la "
        "réparation provisoire est impossible ; clôture GESICA en PRO/QR si la réparation "
        "provisoire est réalisée."
    ),
    "SBL-TRAIT-029::0039": (
        "Si le cas rencontré est : Défaut sur Transport HS sous pression hors zone directe. alors "
        "il faut appliquer l’action suivante : Clôture GESICA en REO/VA si la réparation "
        "provisoire est impossible ; clôture GESICA en PRO/QR si la réparation provisoire est "
        "réalisée."
    ),
    "SBL-TRAIT-029::0040": (
        "Si la réparation provisoire est impossible dans un cas au-dessus du seuil ou hors zone "
        "directe, alors la clôture GESICA doit être réalisée en REO/VA."
    ),
    "SBL-TRAIT-029::0041": (
        "Si une réparation provisoire est réalisée dans un cas au-dessus du seuil ou hors zone "
        "directe, alors la clôture GESICA doit être réalisée en PRO/QR."
    ),
    "SBL-TRAIT-029::0044": (
        "Le contenu de la feuille Excel est porté par une image intégrée ; l’extraction OCR a "
        "initialement laissé un doute sur plusieurs points, résolus le 2026-10-15 par relecture "
        "directe de la capture. Le libellé « Défaut sur câble souterrain > 56 paires » est "
        "confirmé (pas une confusion avec le câble aérien de la ligne précédente). Le code de "
        "clôture est confirmé PRO/QR (pas PRO/OR). Les colonnes « Clôture », « GEM BeB » et "
        "« Réaffecté-BL » contiennent des croix indiquant, pour chaque cas, laquelle des trois "
        "actions s’applique. Les définitions de SBL, GEMBeB, BB, BL et RP restent à confirmer "
        "auprès du référentiel métier. Les articles liés devront être complétés après "
        "transformation des autres feuilles relatives à GESICA, GEMBeB, BL ou SBL."
    ),
    "SBL-TRAIT-029::0045": (
        "Titre de la capture : Tableau de traitement SBL / Actions GESICA. Date associée : Non "
        "indiquée dans la capture ; date de transformation utilisée : 09/06/2026. Description "
        "fonctionnelle : La capture contient un tableau avec une colonne « Cas rencontré » et "
        "trois colonnes d’action GESICA : « Clôture », « GEM BeB » et « Réaffecté-BL ». Les cas "
        "listés portent sur des défauts de câble souterrain, câble aérien, câble multipaires, "
        "réfection d’épissure, RP et Transport HS. Pour les cas sous seuil (GEM BeB), la consigne "
        "textuelle est une ré-injection sur site/SBL ; pour les cas au-dessus du seuil (Clôture), "
        "la consigne est une clôture GESICA directe en REO/VA ou PRO/QR selon qu’une réparation "
        "provisoire a été réalisée. Image source : image intégrée extraite de Traitement SBL.xlsx."
    ),
    "SBL-TRAIT-029::0046": (
        "Question: Quel est le traitement SBL pour un cas sous seuil ?\n"
        "Réponse: Pour les cas sous seuil, la règle visible indique une ré-injection sur "
        "site/SBL en type CLT avec cause BB et BL. Il n’y a pas de clôture directe à ce niveau."
    ),
    "SBL-TRAIT-029::0047": (
        "Question: Quel est le traitement SBL pour un cas au-dessus du seuil ?\n"
        "Réponse: Pour les cas au-dessus du seuil, la règle visible indique une clôture GESICA "
        "directe : en REO/VA si la réparation provisoire est impossible, ou en PRO/QR si elle "
        "est réalisée."
    ),
    "SBL-TRAIT-029::0049": (
        "Question: Quand utiliser REO/VA ?\n"
        "Réponse: REO/VA est indiqué lorsque la réparation provisoire est impossible, pour les "
        "cas au-dessus du seuil ou hors zone directe."
    ),
    "SBL-TRAIT-029::0050": (
        "Question: Quand utiliser PRO/QR ?\n"
        "Réponse: PRO/QR est indiqué lorsque la réparation provisoire est réalisée, pour les cas "
        "au-dessus du seuil ou hors zone directe."
    ),
}

ALL_REPLACEMENTS = {**F04_REPLACEMENTS, **SBL_REPLACEMENTS}


def main() -> None:
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        chunks = json.load(f)

    applied = set()
    for c in chunks:
        cid = c.get("external_chunk_id")
        if cid in ALL_REPLACEMENTS:
            c["text"] = ALL_REPLACEMENTS[cid]
            applied.add(cid)

    missing = set(ALL_REPLACEMENTS) - applied
    if missing:
        raise SystemExit(f"ERROR: {len(missing)} chunk ids not found in chunks.json: {missing}")

    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"Patched {len(applied)} chunks "
          f"({len(F04_REPLACEMENTS)} F04-P03-003, {len(SBL_REPLACEMENTS)} SBL-TRAIT-029).")


if __name__ == "__main__":
    main()
