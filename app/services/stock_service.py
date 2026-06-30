"""
Logique metier des mouvements de stock : entrees, sorties, ajustements.

Regle d'or : la mise a jour des champs caches Produit.quantite_stock et
Produit.pmp ne doit JAMAIS se faire ailleurs que dans ce module, afin de
garantir la coherence comptable du stock.
"""

from datetime import datetime, date

from sqlalchemy import func

from app.extensions import db
from app.models import Lot, Mouvement, MouvementLot, Produit, TypeMouvement


class StockError(Exception):
    """Erreur de gestion de stock (ex: stock insuffisant)."""


def _arrondi_qte(valeur):
    return round(valeur, 3)


def _arrondi_valeur(valeur):
    return round(valeur, 2)


def convertir_en_unite_gestion(produit, quantite, unite="GESTION"):
    """Convertit une quantite saisie en unite d'ACHAT ou de GESTION
    vers l'unite de GESTION (unite de reference du stock)."""
    if unite.upper() == "ACHAT":
        return quantite * (produit.facteur_conversion or 1.0)
    return quantite


def convertir_cout_en_unite_gestion(produit, cout_unitaire, unite="GESTION"):
    """Convertit un cout unitaire saisi en unite d'ACHAT ou de GESTION
    vers un cout par unite de GESTION."""
    if unite.upper() == "ACHAT":
        facteur = produit.facteur_conversion or 1.0
        return cout_unitaire / facteur if facteur else cout_unitaire
    return cout_unitaire


def generer_numero_lot(produit, date_reference=None):
    date_reference = date_reference or date.today()
    prefixe = f"{produit.code}-{date_reference.strftime('%Y%m%d')}"
    nb_existants = Lot.query.filter(
        Lot.produit_id == produit.id, Lot.numero_lot.like(f"{prefixe}%")
    ).count()
    return f"{prefixe}-{nb_existants + 1:03d}"


def enregistrer_entree(
    produit,
    quantite,
    cout_unitaire,
    unite="GESTION",
    numero_lot=None,
    date_entree=None,
    date_expiration=None,
    depot_id=None,
    tiers_id=None,
    reference=None,
    motif=None,
    utilisateur="systeme",
    type_mouvement=TypeMouvement.ENTREE,
):
    """Enregistre une entree en stock : cree un nouveau lot et recalcule le PMP.

    - `quantite` et `cout_unitaire` sont exprimes dans l'unite indiquee par
      `unite` ("ACHAT" ou "GESTION"). Ils sont convertis en unite de gestion.
    - `tiers_id` : origine de l'entree (fournisseur), pour permettre une
      analyse des mouvements par partenaire.
    """
    if quantite is None or quantite <= 0:
        raise StockError("La quantite d'entree doit etre superieure a zero.")
    if cout_unitaire is None or cout_unitaire < 0:
        raise StockError("Le cout unitaire doit etre positif ou nul.")

    qte_gestion = _arrondi_qte(convertir_en_unite_gestion(produit, quantite, unite))
    cout_gestion = convertir_cout_en_unite_gestion(produit, cout_unitaire, unite)

    date_entree = date_entree or date.today()
    if not numero_lot:
        numero_lot = generer_numero_lot(produit, date_entree)

    # 1. Creation du lot
    lot = Lot(
        produit_id=produit.id,
        depot_id=depot_id,
        numero_lot=numero_lot,
        date_entree=date_entree,
        date_expiration=date_expiration,
        quantite_initiale=qte_gestion,
        quantite_restante=qte_gestion,
        cout_unitaire_achat=_arrondi_valeur(cout_gestion),
    )
    db.session.add(lot)

    # 2. Recalcul du PMP (Cout Unitaire Moyen Pondere)
    stock_avant = produit.quantite_stock or 0.0
    pmp_avant = produit.pmp or 0.0
    nouveau_stock = stock_avant + qte_gestion
    if nouveau_stock > 0:
        nouveau_pmp = ((stock_avant * pmp_avant) + (qte_gestion * cout_gestion)) / nouveau_stock
    else:
        nouveau_pmp = cout_gestion

    produit.quantite_stock = _arrondi_qte(nouveau_stock)
    produit.pmp = _arrondi_valeur(nouveau_pmp)

    # 3. Mouvement (tracabilite)
    mouvement = Mouvement(
        type_mouvement=type_mouvement,
        produit_id=produit.id,
        depot_id=depot_id,
        tiers_id=tiers_id,
        date_mouvement=datetime.utcnow(),
        quantite=qte_gestion,
        cout_unitaire=_arrondi_valeur(cout_gestion),
        valeur=_arrondi_valeur(qte_gestion * cout_gestion),
        pmp_apres=produit.pmp,
        stock_apres=produit.quantite_stock,
        reference=reference,
        motif=motif,
        utilisateur=utilisateur,
    )
    db.session.add(mouvement)
    db.session.flush()  # pour obtenir mouvement.id et lot.id

    db.session.add(MouvementLot(mouvement_id=mouvement.id, lot_id=lot.id, quantite=qte_gestion))

    db.session.commit()
    return mouvement


def enregistrer_sortie(
    produit,
    quantite,
    unite="GESTION",
    depot_id=None,
    tiers_id=None,
    reference=None,
    motif=None,
    date_mouvement=None,
    utilisateur="systeme",
    type_mouvement=TypeMouvement.SORTIE,
):
    """Enregistre une sortie de stock. Les lots sont consommes en FIFO
    (date d'entree la plus ancienne en premier), **a l'interieur du depot
    indique** : une sortie d'un depot ne peut consommer que les lots
    physiquement localises dans ce depot. La valorisation de la sortie se
    fait au PMP courant du produit (le PMP n'est pas modifie par une sortie).

    Si `depot_id` est None (mode herite / pas de depot precise), le
    comportement bascule sur le stock et les lots consolides tous depots
    confondus.

    `tiers_id` : consommateur / destinataire de la sortie (client, service,
    atelier...), pour permettre une analyse des mouvements par partenaire."""
    if quantite is None or quantite <= 0:
        raise StockError("La quantite de sortie doit etre superieure a zero.")

    qte_gestion = _arrondi_qte(convertir_en_unite_gestion(produit, quantite, unite))

    requete_lots = Lot.query.filter(Lot.produit_id == produit.id, Lot.quantite_restante > 0)

    if depot_id is not None:
        stock_disponible = quantite_stock_depot(produit.id, depot_id)
        if qte_gestion > stock_disponible + 1e-6:
            raise StockError(
                f"Stock insuffisant pour {produit.designation} dans ce depot : "
                f"disponible {stock_disponible} {produit.unite_gestion.code}, "
                f"demande {qte_gestion} {produit.unite_gestion.code}."
            )
        requete_lots = requete_lots.filter(Lot.depot_id == depot_id)
    else:
        if qte_gestion > (produit.quantite_stock or 0.0) + 1e-6:
            raise StockError(
                f"Stock insuffisant pour {produit.designation} : "
                f"disponible {produit.quantite_stock} {produit.unite_gestion.code}, "
                f"demande {qte_gestion} {produit.unite_gestion.code}."
            )

    # Selection des lots disponibles par ordre FIFO (date d'entree croissante)
    lots_disponibles = requete_lots.order_by(Lot.date_entree.asc(), Lot.id.asc()).all()

    pmp_courant = produit.pmp or 0.0
    qte_restant_a_sortir = qte_gestion
    allocations = []  # (lot, quantite_prelevee)

    for lot in lots_disponibles:
        if qte_restant_a_sortir <= 0:
            break
        prelevement = min(lot.quantite_restante, qte_restant_a_sortir)
        if prelevement <= 0:
            continue
        lot.quantite_restante = _arrondi_qte(lot.quantite_restante - prelevement)
        qte_restant_a_sortir = _arrondi_qte(qte_restant_a_sortir - prelevement)
        allocations.append((lot, prelevement))

    if qte_restant_a_sortir > 1e-6:
        # Securite : ne devrait pas arriver si quantite_stock est coherent avec les lots
        raise StockError(
            "Incoherence de stock detectee : quantite disponible dans les lots "
            "inferieure a la quantite en stock enregistree. Veuillez verifier les lots."
        )

    produit.quantite_stock = _arrondi_qte((produit.quantite_stock or 0.0) - qte_gestion)
    # Le PMP reste inchange lors d'une sortie.

    mouvement = Mouvement(
        type_mouvement=type_mouvement,
        produit_id=produit.id,
        depot_id=depot_id,
        tiers_id=tiers_id,
        date_mouvement=date_mouvement or datetime.utcnow(),
        quantite=qte_gestion,
        cout_unitaire=_arrondi_valeur(pmp_courant),
        valeur=_arrondi_valeur(qte_gestion * pmp_courant),
        pmp_apres=produit.pmp,
        stock_apres=produit.quantite_stock,
        reference=reference,
        motif=motif,
        utilisateur=utilisateur,
    )
    db.session.add(mouvement)
    db.session.flush()

    for lot, prelevement in allocations:
        db.session.add(
            MouvementLot(mouvement_id=mouvement.id, lot_id=lot.id, quantite=prelevement)
        )

    db.session.commit()
    return mouvement


def enregistrer_ajustement(
    produit,
    quantite_delta,
    motif,
    unite="GESTION",
    depot_id=None,
    tiers_id=None,
    reference=None,
    utilisateur="systeme",
):
    """Ajustement manuel de stock (inventaire physique, casse, perte...).
    `quantite_delta` positif = ajustement a la hausse, negatif = a la baisse.
    Un ajustement a la baisse consomme des lots en FIFO comme une sortie.
    Un ajustement a la hausse cree un lot au PMP courant (cout inconnu)."""
    if quantite_delta == 0:
        raise StockError("La quantite d'ajustement ne peut pas etre nulle.")

    qte_gestion = convertir_en_unite_gestion(produit, abs(quantite_delta), unite)

    if quantite_delta > 0:
        return enregistrer_entree(
            produit,
            qte_gestion,
            cout_unitaire=produit.pmp or 0.0,
            unite="GESTION",
            depot_id=depot_id,
            tiers_id=tiers_id,
            reference=reference,
            motif=motif or "Ajustement positif (inventaire)",
            utilisateur=utilisateur,
            type_mouvement=TypeMouvement.AJUSTEMENT_POSITIF,
        )
    else:
        return enregistrer_sortie(
            produit,
            qte_gestion,
            unite="GESTION",
            depot_id=depot_id,
            tiers_id=tiers_id,
            reference=reference,
            motif=motif or "Ajustement negatif (inventaire)",
            utilisateur=utilisateur,
            type_mouvement=TypeMouvement.AJUSTEMENT_NEGATIF,
        )


def annuler_mouvement(mouvement, utilisateur="systeme"):
    """Annule un mouvement de stock (entree, sortie ou ajustement).

    Restriction volontaire : seul le **tout dernier mouvement enregistre
    pour ce produit** (tous depots confondus) peut etre annule. Le PMP et les
    lots sont en effet construits de facon sequentielle (chaque mouvement
    depend de l'etat laisse par le precedent) : annuler un mouvement plus
    ancien sans toucher aux mouvements posterieurs casserait la coherence du
    PMP et des quantites de lots. Pour corriger un mouvement plus ancien, il
    faut passer par un mouvement correctif (nouvelle entree/sortie/ajustement).

    L'annulation ne supprime pas le mouvement original (tracabilite) : elle
    le marque `annule=True` et cree un mouvement compensatoire
    (`type_mouvement=ANNULATION`) qui neutralise son effet sur le stock.
    """
    if mouvement.annule:
        raise StockError("Ce mouvement a deja ete annule.")
    if mouvement.est_annulation:
        raise StockError("Une annulation ne peut pas elle-meme etre annulee.")

    dernier = (
        Mouvement.query.filter_by(produit_id=mouvement.produit_id)
        .order_by(Mouvement.id.desc())
        .first()
    )
    if dernier is None or dernier.id != mouvement.id:
        raise StockError(
            "Seul le tout dernier mouvement enregistre pour ce produit peut etre "
            "annule, afin de preserver la coherence du PMP et des lots. "
            "Effectuez plutot un mouvement correctif (entree, sortie ou ajustement)."
        )

    produit = mouvement.produit
    type_origine = mouvement.type_mouvement

    if type_origine in (TypeMouvement.ENTREE, TypeMouvement.AJUSTEMENT_POSITIF):
        lignes = list(mouvement.lignes_lot)
        if len(lignes) != 1:
            raise StockError(
                "Mouvement d'entree incoherent (lot introuvable) : annulation impossible."
            )
        ligne = lignes[0]
        lot = ligne.lot
        if abs(lot.quantite_restante - lot.quantite_initiale) > 1e-6:
            raise StockError(
                "Le lot cree par cette entree a deja ete partiellement consomme : "
                "annulation impossible."
            )

        stock_avant = _arrondi_qte(mouvement.stock_apres - mouvement.quantite)
        if stock_avant > 1e-9:
            pmp_avant = _arrondi_valeur(
                (mouvement.stock_apres * mouvement.pmp_apres - mouvement.quantite * mouvement.cout_unitaire)
                / stock_avant
            )
        else:
            stock_avant = 0.0
            pmp_avant = 0.0

        produit.quantite_stock = stock_avant
        produit.pmp = pmp_avant

        db.session.delete(ligne)
        db.session.delete(lot)

    elif type_origine in (TypeMouvement.SORTIE, TypeMouvement.AJUSTEMENT_NEGATIF):
        for ligne in list(mouvement.lignes_lot):
            lot = ligne.lot
            lot.quantite_restante = _arrondi_qte(lot.quantite_restante + ligne.quantite)
        produit.quantite_stock = _arrondi_qte((produit.quantite_stock or 0.0) + mouvement.quantite)
        # Le PMP n'est pas modifie par une sortie, il ne l'est donc pas non plus par son annulation.

    else:
        raise StockError(
            f"Annulation non prise en charge pour le type de mouvement {type_origine}."
        )

    maintenant = datetime.utcnow()
    mouvement.annule = True
    mouvement.annule_par = utilisateur
    mouvement.date_annulation = maintenant

    compensation = Mouvement(
        type_mouvement=TypeMouvement.ANNULATION,
        produit_id=produit.id,
        depot_id=mouvement.depot_id,
        tiers_id=mouvement.tiers_id,
        date_mouvement=maintenant,
        quantite=mouvement.quantite,
        cout_unitaire=mouvement.cout_unitaire,
        valeur=mouvement.valeur,
        pmp_apres=produit.pmp,
        stock_apres=produit.quantite_stock,
        reference=mouvement.reference,
        motif=f"Annulation du mouvement #{mouvement.id} ({TypeMouvement.libelle(type_origine)})",
        utilisateur=utilisateur,
        est_annulation=True,
        mouvement_origine_id=mouvement.id,
    )
    db.session.add(compensation)
    db.session.commit()
    return compensation


def quantite_stock_depot(produit_id, depot_id):
    """Quantite actuellement en stock (unite de gestion) pour un produit dans
    un depot donne, calculee a partir des lots (somme des quantites restantes
    des lots localises dans ce depot)."""
    if depot_id is None:
        return 0.0
    total = (
        db.session.query(func.coalesce(func.sum(Lot.quantite_restante), 0.0))
        .filter(Lot.produit_id == produit_id, Lot.depot_id == depot_id)
        .scalar()
    )
    return total or 0.0


def get_alertes_stock_securite():
    """Retourne la liste des produits actifs dont le stock est au niveau
    ou en dessous du stock de securite defini."""
    produits = Produit.query.filter(Produit.actif.is_(True), Produit.stock_securite > 0).all()
    return [p for p in produits if p.quantite_stock <= p.stock_securite]
