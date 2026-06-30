from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import AccesDepot, Depot, NiveauUtilisateur, Utilisateur
from app.services.permissions import admin_requis

bp = Blueprint("utilisateurs", __name__)


@bp.route("/")
@admin_requis
def liste():
    utilisateurs = Utilisateur.query.order_by(Utilisateur.nom.asc()).all()
    return render_template("utilisateurs/liste.html", utilisateurs=utilisateurs)


@bp.route("/nouveau", methods=["GET", "POST"])
@admin_requis
def nouveau():
    depots = Depot.query.filter_by(actif=True).order_by(Depot.code.asc()).all()

    if request.method == "POST":
        try:
            utilisateur = Utilisateur(
                nom=request.form["nom"].strip(),
                email=request.form["email"].strip().lower(),
                est_admin=bool(request.form.get("est_admin")),
                actif=bool(request.form.get("actif", "on")),
                recevoir_alertes_email=bool(request.form.get("recevoir_alertes_email")),
                niveau=request.form.get("niveau", type=int) or NiveauUtilisateur.STANDARD,
            )
            utilisateur.definir_mot_de_passe(request.form["mot_de_passe"])
            db.session.add(utilisateur)
            db.session.flush()

            _enregistrer_acces_depots(utilisateur, depots)

            db.session.commit()
            flash(f"Utilisateur {utilisateur.email} cree.", "success")
            return redirect(url_for("utilisateurs.liste"))
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            flash(f"Erreur lors de la creation : {exc}", "danger")

    return render_template(
        "utilisateurs/form.html",
        utilisateur=None,
        depots=depots,
        acces={},
        niveaux=NiveauUtilisateur.CHOIX,
    )


@bp.route("/<int:utilisateur_id>/modifier", methods=["GET", "POST"])
@admin_requis
def modifier(utilisateur_id):
    utilisateur = Utilisateur.query.get_or_404(utilisateur_id)
    depots = Depot.query.filter_by(actif=True).order_by(Depot.code.asc()).all()

    if request.method == "POST":
        try:
            utilisateur.nom = request.form["nom"].strip()
            utilisateur.email = request.form["email"].strip().lower()
            utilisateur.est_admin = bool(request.form.get("est_admin"))
            utilisateur.actif = bool(request.form.get("actif"))
            utilisateur.recevoir_alertes_email = bool(request.form.get("recevoir_alertes_email"))
            utilisateur.niveau = request.form.get("niveau", type=int) or NiveauUtilisateur.STANDARD

            nouveau_mot_de_passe = request.form.get("mot_de_passe", "").strip()
            if nouveau_mot_de_passe:
                utilisateur.definir_mot_de_passe(nouveau_mot_de_passe)

            _enregistrer_acces_depots(utilisateur, depots)

            db.session.commit()
            flash(f"Utilisateur {utilisateur.email} mis a jour.", "success")
            return redirect(url_for("utilisateurs.liste"))
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            flash(f"Erreur lors de la mise a jour : {exc}", "danger")

    acces = {a.depot_id: a for a in utilisateur.acces_depots}
    return render_template(
        "utilisateurs/form.html",
        utilisateur=utilisateur,
        depots=depots,
        acces=acces,
        niveaux=NiveauUtilisateur.CHOIX,
    )


def _enregistrer_acces_depots(utilisateur, depots):
    """Met a jour les lignes AccesDepot a partir des cases cochees du formulaire :
    pour chaque depot, deux checkboxes `lecture_<id>` et `ecriture_<id>`."""
    acces_existants = {a.depot_id: a for a in utilisateur.acces_depots}

    for depot in depots:
        peut_lire = bool(request.form.get(f"lecture_{depot.id}"))
        peut_ecrire = bool(request.form.get(f"ecriture_{depot.id}"))

        if depot.id in acces_existants:
            ligne = acces_existants[depot.id]
            if peut_lire or peut_ecrire:
                ligne.peut_lire = peut_lire
                ligne.peut_ecrire = peut_ecrire
            else:
                db.session.delete(ligne)
        elif peut_lire or peut_ecrire:
            db.session.add(
                AccesDepot(
                    utilisateur_id=utilisateur.id,
                    depot_id=depot.id,
                    peut_lire=peut_lire,
                    peut_ecrire=peut_ecrire,
                )
            )
