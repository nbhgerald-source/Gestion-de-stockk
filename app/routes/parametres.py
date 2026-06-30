from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Depot, Tiers, TypeTiers, UniteMesure
from app.services.permissions import admin_requis

bp = Blueprint("parametres", __name__)


@bp.route("/unites", methods=["GET", "POST"])
@admin_requis
def unites():
    if request.method == "POST":
        try:
            unite = UniteMesure(
                code=request.form["code"].strip().upper(),
                libelle=request.form["libelle"].strip(),
            )
            db.session.add(unite)
            db.session.commit()
            flash(f"Unite {unite.code} ajoutee.", "success")
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            flash(f"Erreur : {exc}", "danger")
        return redirect(url_for("parametres.unites"))

    liste_unites = UniteMesure.query.order_by(UniteMesure.code.asc()).all()
    return render_template("parametres/unites.html", unites=liste_unites)


@bp.route("/depots", methods=["GET", "POST"])
@admin_requis
def depots():
    if request.method == "POST":
        try:
            depot = Depot(
                code=request.form["code"].strip().upper(),
                nom=request.form["nom"].strip(),
            )
            db.session.add(depot)
            db.session.commit()
            flash(f"Depot {depot.code} ajoute.", "success")
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            flash(f"Erreur : {exc}", "danger")
        return redirect(url_for("parametres.depots"))

    liste_depots = Depot.query.order_by(Depot.code.asc()).all()
    return render_template("parametres/depots.html", depots=liste_depots)


@bp.route("/tiers", methods=["GET", "POST"])
@admin_requis
def tiers():
    """CRUD des tiers (fournisseurs / clients-consommateurs / autres), utilises
    comme origine d'une entree ou destinataire/consommateur d'une sortie, pour
    permettre une analyse des mouvements par partenaire."""
    if request.method == "POST":
        try:
            partenaire = Tiers(
                code=request.form["code"].strip().upper(),
                nom=request.form["nom"].strip(),
                type_tiers=request.form.get("type_tiers", TypeTiers.AUTRE),
            )
            db.session.add(partenaire)
            db.session.commit()
            flash(f"Tiers {partenaire.code} ajoute.", "success")
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            flash(f"Erreur : {exc}", "danger")
        return redirect(url_for("parametres.tiers"))

    liste_tiers = Tiers.query.order_by(Tiers.code.asc()).all()
    return render_template(
        "parametres/tiers.html", tiers_liste=liste_tiers, types_tiers=TypeTiers.CHOIX
    )
