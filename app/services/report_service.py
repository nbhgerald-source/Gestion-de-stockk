"""
Generation des rapports de stock periodiques (journalier, hebdomadaire,
mensuel, trimestriel, annuel).

Principe : chaque Mouvement enregistre l'etat du produit (quantite et PMP)
immediatement APRES son execution (champs stock_apres / pmp_apres). Pour
obtenir l'etat du stock a une date donnee, il suffit de retrouver le dernier
mouvement survenu a cette date (ou avant) -- pas besoin de "rejouer"
l'historique complet, ce qui rend les rapports rapides et fiables.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta

from sqlalchemy import case, func

from app.extensions import db
from app.models import Mouvement, Produit, Tiers, TypeMouvement


PERIODES = [
    ("JOUR", "Journalier"),
    ("SEMAINE", "Hebdomadaire"),
    ("MOIS", "Mensuel"),
    ("TRIMESTRE", "Trimestriel"),
    ("ANNEE", "Annuel"),
]


def calculer_bornes_periode(type_periode, date_reference=None):
    """Retourne (debut, fin) en datetime, bornes incluses, pour le type de
    periode demande contenant `date_reference`."""
    date_reference = date_reference or date.today()
    type_periode = (type_periode or "JOUR").upper()

    if type_periode == "JOUR":
        debut_j = date_reference
        fin_j = date_reference
    elif type_periode == "SEMAINE":
        debut_j = date_reference - timedelta(days=date_reference.weekday())  # lundi
        fin_j = debut_j + timedelta(days=6)  # dimanche
    elif type_periode == "MOIS":
        debut_j = date_reference.replace(day=1)
        dernier_jour = monthrange(date_reference.year, date_reference.month)[1]
        fin_j = date_reference.replace(day=dernier_jour)
    elif type_periode == "TRIMESTRE":
        trimestre = (date_reference.month - 1) // 3  # 0..3
        mois_debut = trimestre * 3 + 1
        debut_j = date(date_reference.year, mois_debut, 1)
        mois_fin = mois_debut + 2
        dernier_jour = monthrange(date_reference.year, mois_fin)[1]
        fin_j = date(date_reference.year, mois_fin, dernier_jour)
    elif type_periode == "ANNEE":
        debut_j = date(date_reference.year, 1, 1)
        fin_j = date(date_reference.year, 12, 31)
    else:
        raise ValueError(f"Type de periode inconnu : {type_periode}")

    debut = datetime.combine(debut_j, datetime.min.time())
    fin = datetime.combine(fin_j, datetime.max.time())
    return debut, fin


def _etat_a_la_date(produit_id, date_limite):
    """Dernier mouvement du produit a `date_limite` (datetime) ou avant,
    TOUS DEPOTS CONFONDUS (lecture rapide via le cache stock_apres/pmp_apres).
    Retourne (quantite, pmp) ; (0.0, 0.0) si aucun mouvement."""
    mouvement = (
        Mouvement.query.filter(
            Mouvement.produit_id == produit_id, Mouvement.date_mouvement <= date_limite
        )
        .order_by(Mouvement.date_mouvement.desc(), Mouvement.id.desc())
        .first()
    )
    if mouvement is None:
        return 0.0, 0.0
    return mouvement.stock_apres, mouvement.pmp_apres


def _quantite_depots_a_la_date(produit_id, depot_ids, date_limite):
    """Quantite en stock (unite de gestion) pour un produit, restreinte a un
    sous-ensemble de depots (`depot_ids`), a une date donnee. Calculee en
    rejouant la somme signee des mouvements de ces depots jusqu'a la date
    (necessaire car le cache stock_apres est, lui, consolide tous depots)."""
    delta_signe = case(
        (Mouvement.type_mouvement.in_([TypeMouvement.ENTREE, TypeMouvement.AJUSTEMENT_POSITIF]),
         Mouvement.quantite),
        else_=-Mouvement.quantite,
    )
    total = (
        db.session.query(func.coalesce(func.sum(delta_signe), 0.0))
        .filter(
            Mouvement.produit_id == produit_id,
            Mouvement.depot_id.in_(depot_ids),
            Mouvement.date_mouvement <= date_limite,
        )
        .scalar()
    )
    return total or 0.0


def generer_rapport_stock(
    type_periode, date_reference=None, type_produit=None, produit_id=None, depot_ids=None
):
    """Construit le rapport de stock pour la periode demandee.

    `depot_ids` :
        - None  -> rapport CONSOLIDE tous depots confondus (chemin rapide,
          utilise les compteurs caches sur Produit/Mouvement).
        - liste d'identifiants de depots -> rapport restreint a ces depots
          (un seul depot pour un rapport "par depot", ou plusieurs pour un
          consolide partiel correspondant aux depots autorises d'un utilisateur).
          Le PMP utilise pour valoriser reste le PMP global de l'entreprise
          (le cout moyen pondere n'est pas suivi separement par depot).

    Retourne un dict :
        {
            "periode": {"type", "debut", "fin"},
            "lignes": [ {produit, stock_initial_qte, stock_initial_valeur,
                          entrees_qte, entrees_valeur, sorties_qte, sorties_valeur,
                          stock_final_qte, stock_final_valeur}, ... ],
            "totaux": {...}
        }
    """
    debut, fin = calculer_bornes_periode(type_periode, date_reference)

    requete = Produit.query.filter(Produit.actif.is_(True))
    if type_produit:
        requete = requete.filter(Produit.type_produit == type_produit)
    if produit_id:
        requete = requete.filter(Produit.id == produit_id)
    produits = requete.order_by(Produit.code.asc()).all()

    lignes = []
    totaux = {
        "stock_initial_valeur": 0.0,
        "entrees_qte": 0.0,
        "entrees_valeur": 0.0,
        "sorties_qte": 0.0,
        "sorties_valeur": 0.0,
        "stock_final_valeur": 0.0,
    }

    for produit in produits:
        if depot_ids is None:
            qte_initiale, pmp_initial = _etat_a_la_date(produit.id, debut - timedelta(microseconds=1))
            qte_finale, pmp_final = _etat_a_la_date(produit.id, fin)
        else:
            qte_initiale = _quantite_depots_a_la_date(produit.id, depot_ids, debut - timedelta(microseconds=1))
            qte_finale = _quantite_depots_a_la_date(produit.id, depot_ids, fin)
            # Le PMP n'est pas suivi par depot : on reutilise le PMP global de
            # l'entreprise (coherent avec la regle "un seul PMP par produit").
            _, pmp_initial = _etat_a_la_date(produit.id, debut - timedelta(microseconds=1))
            _, pmp_final = _etat_a_la_date(produit.id, fin)

        requete_mouvements = Mouvement.query.filter(
            Mouvement.produit_id == produit.id,
            Mouvement.date_mouvement >= debut,
            Mouvement.date_mouvement <= fin,
        )
        if depot_ids is not None:
            requete_mouvements = requete_mouvements.filter(Mouvement.depot_id.in_(depot_ids))
        mouvements_periode = requete_mouvements.all()

        entrees_qte = sum(
            m.quantite for m in mouvements_periode
            if m.type_mouvement in (TypeMouvement.ENTREE, TypeMouvement.AJUSTEMENT_POSITIF)
        )
        entrees_valeur = sum(
            m.valeur for m in mouvements_periode
            if m.type_mouvement in (TypeMouvement.ENTREE, TypeMouvement.AJUSTEMENT_POSITIF)
        )
        sorties_qte = sum(
            m.quantite for m in mouvements_periode
            if m.type_mouvement in (TypeMouvement.SORTIE, TypeMouvement.AJUSTEMENT_NEGATIF)
        )
        sorties_valeur = sum(
            m.valeur for m in mouvements_periode
            if m.type_mouvement in (TypeMouvement.SORTIE, TypeMouvement.AJUSTEMENT_NEGATIF)
        )

        ligne = {
            "produit": produit,
            "stock_initial_qte": round(qte_initiale, 3),
            "stock_initial_valeur": round(qte_initiale * pmp_initial, 2),
            "entrees_qte": round(entrees_qte, 3),
            "entrees_valeur": round(entrees_valeur, 2),
            "sorties_qte": round(sorties_qte, 3),
            "sorties_valeur": round(sorties_valeur, 2),
            "stock_final_qte": round(qte_finale, 3),
            "stock_final_valeur": round(qte_finale * pmp_final, 2),
        }
        lignes.append(ligne)

        totaux["stock_initial_valeur"] += ligne["stock_initial_valeur"]
        totaux["entrees_qte"] += ligne["entrees_qte"]
        totaux["entrees_valeur"] += ligne["entrees_valeur"]
        totaux["sorties_qte"] += ligne["sorties_qte"]
        totaux["sorties_valeur"] += ligne["sorties_valeur"]
        totaux["stock_final_valeur"] += ligne["stock_final_valeur"]

    for cle in totaux:
        totaux[cle] = round(totaux[cle], 2)

    return {
        "periode": {"type": type_periode, "debut": debut, "fin": fin},
        "lignes": lignes,
        "totaux": totaux,
    }


def rapport_par_tiers(type_periode, date_reference=None, depot_ids=None):
    """Construit un rapport agregeant les mouvements de la periode par tiers
    (fournisseur a l'origine d'une entree, client/consommateur destinataire
    d'une sortie), afin d'analyser les volumes et valeurs par partenaire.

    `depot_ids` : meme convention que `generer_rapport_stock` (None = tous
    depots, liste = restriction a ces depots)."""
    debut, fin = calculer_bornes_periode(type_periode, date_reference)

    entree_like = Mouvement.type_mouvement.in_([TypeMouvement.ENTREE, TypeMouvement.AJUSTEMENT_POSITIF])
    sortie_like = Mouvement.type_mouvement.in_([TypeMouvement.SORTIE, TypeMouvement.AJUSTEMENT_NEGATIF])

    requete = db.session.query(
        Mouvement.tiers_id,
        func.sum(case((entree_like, Mouvement.quantite), else_=0.0)).label("entrees_qte"),
        func.sum(case((entree_like, Mouvement.valeur), else_=0.0)).label("entrees_valeur"),
        func.sum(case((sortie_like, Mouvement.quantite), else_=0.0)).label("sorties_qte"),
        func.sum(case((sortie_like, Mouvement.valeur), else_=0.0)).label("sorties_valeur"),
    ).filter(Mouvement.date_mouvement >= debut, Mouvement.date_mouvement <= fin)

    if depot_ids is not None:
        requete = requete.filter(Mouvement.depot_id.in_(depot_ids))

    resultats = requete.group_by(Mouvement.tiers_id).all()
    tiers_par_id = {t.id: t for t in Tiers.query.all()}

    lignes = []
    totaux = {"entrees_qte": 0.0, "entrees_valeur": 0.0, "sorties_qte": 0.0, "sorties_valeur": 0.0}

    for tiers_id, entrees_qte, entrees_valeur, sorties_qte, sorties_valeur in resultats:
        ligne = {
            "tiers": tiers_par_id.get(tiers_id),
            "entrees_qte": round(entrees_qte or 0.0, 3),
            "entrees_valeur": round(entrees_valeur or 0.0, 2),
            "sorties_qte": round(sorties_qte or 0.0, 3),
            "sorties_valeur": round(sorties_valeur or 0.0, 2),
        }
        lignes.append(ligne)
        totaux["entrees_qte"] += ligne["entrees_qte"]
        totaux["entrees_valeur"] += ligne["entrees_valeur"]
        totaux["sorties_qte"] += ligne["sorties_qte"]
        totaux["sorties_valeur"] += ligne["sorties_valeur"]

    lignes.sort(key=lambda l: (l["tiers"].code if l["tiers"] else "~ Non precise"))
    for cle in totaux:
        totaux[cle] = round(totaux[cle], 2)

    return {
        "periode": {"type": type_periode, "debut": debut, "fin": fin},
        "lignes": lignes,
        "totaux": totaux,
    }
