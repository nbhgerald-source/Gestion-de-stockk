"""
Aide a la gestion des droits d'acces par depot.

Regle generale :
- Un utilisateur `est_admin` a acces total (lecture + ecriture, tous depots).
- Un utilisateur standard n'a acces qu'aux depots pour lesquels une ligne
  `AccesDepot` existe, avec `peut_lire` et/ou `peut_ecrire` a True.
- `depots_lecture_ids` / `depots_ecriture_ids` renvoient `None` pour signifier
  "tous les depots" (cas admin), ou une liste d'identifiants de depots sinon.
"""

from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from app.models import Depot, NiveauUtilisateur, Utilisateur


class AccesRefuse(Exception):
    """Levee quand un utilisateur tente une action sur un depot non autorise."""


def depots_visibles(utilisateur):
    """Liste des Depot que l'utilisateur peut consulter (lecture).
    Renvoie tous les depots actifs si admin."""
    if utilisateur.est_admin:
        return Depot.query.filter_by(actif=True).order_by(Depot.code.asc()).all()
    ids = utilisateur.depots_lecture_ids or []
    if not ids:
        return []
    return Depot.query.filter(Depot.id.in_(ids), Depot.actif.is_(True)).order_by(Depot.code.asc()).all()


def depots_modifiables(utilisateur):
    """Liste des Depot sur lesquels l'utilisateur peut saisir des mouvements (ecriture)."""
    if utilisateur.est_admin:
        return Depot.query.filter_by(actif=True).order_by(Depot.code.asc()).all()
    ids = utilisateur.depots_ecriture_ids or []
    if not ids:
        return []
    return Depot.query.filter(Depot.id.in_(ids), Depot.actif.is_(True)).order_by(Depot.code.asc()).all()


def verifier_lecture_depot(utilisateur, depot_id):
    if depot_id is None:
        return  # acces "consolide" : filtre deja au niveau de la requete (depots_lecture_ids)
    if not utilisateur.peut_lire_depot(depot_id):
        raise AccesRefuse(f"Acces en lecture refuse pour le depot {depot_id}.")


def verifier_ecriture_depot(utilisateur, depot_id):
    if depot_id is None:
        raise AccesRefuse("Un depot doit etre selectionne pour cette operation.")
    if not utilisateur.peut_ecrire_depot(depot_id):
        raise AccesRefuse(f"Acces en ecriture refuse pour le depot {depot_id}.")


def peut_annuler_mouvement(utilisateur, mouvement):
    """Un utilisateur peut annuler un mouvement si :
    - il a un droit d'**ecriture** sur le depot du mouvement (ou est
      administrateur si le mouvement n'a pas de depot precise) ; ET
    - son **niveau** (`niveau_effectif`) est strictement superieur a celui de
      l'auteur du mouvement (`mouvement.utilisateur`, un email). Un auteur
      introuvable (ex: "systeme") est considere de niveau Standard.
    """
    if mouvement.depot_id is not None:
        if not utilisateur.peut_ecrire_depot(mouvement.depot_id):
            return False
    elif not utilisateur.est_admin:
        return False

    auteur = Utilisateur.query.filter_by(email=mouvement.utilisateur).first()
    niveau_auteur = auteur.niveau_effectif if auteur else NiveauUtilisateur.STANDARD
    return utilisateur.niveau_effectif > niveau_auteur


def admin_requis(vue):
    """Decorateur : reserve une route aux administrateurs."""

    @wraps(vue)
    def enveloppe(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.est_admin:
            flash("Cette action est reservee aux administrateurs.", "danger")
            return redirect(url_for("main.dashboard"))
        return vue(*args, **kwargs)

    return enveloppe
