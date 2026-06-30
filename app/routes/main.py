from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.models import Produit, TypeProduit
from app.services.mail_service import MailError, envoyer_alertes_stock
from app.services.stock_service import get_alertes_stock_securite

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def dashboard():
    produits = Produit.query.filter_by(actif=True).all()
    valeur_totale_stock = round(sum(p.valeur_stock for p in produits), 2)
    nb_produits = len(produits)
    alertes = get_alertes_stock_securite()

    repartition_par_type = []
    for code, libelle in TypeProduit.CHOIX:
        sous_ensemble = [p for p in produits if p.type_produit == code]
        repartition_par_type.append(
            {
                "libelle": libelle,
                "nb_produits": len(sous_ensemble),
                "valeur": round(sum(p.valeur_stock for p in sous_ensemble), 2),
            }
        )

    return render_template(
        "dashboard.html",
        nb_produits=nb_produits,
        valeur_totale_stock=valeur_totale_stock,
        alertes=alertes,
        nb_alertes=len(alertes),
        repartition_par_type=repartition_par_type,
    )


@bp.route("/alertes/envoyer-email", methods=["POST"])
@login_required
def envoyer_alertes_email():
    alertes = get_alertes_stock_securite()
    try:
        envoye, destinataires = envoyer_alertes_stock(alertes)
    except MailError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.dashboard"))

    if not alertes:
        flash("Aucune alerte de stock de securite a signaler.", "info")
    elif not envoye:
        flash(
            "Aucun utilisateur n'est inscrit aux alertes par email "
            "(a activer dans Utilisateurs > Modifier).",
            "warning",
        )
    else:
        flash(f"Alertes envoyees a {len(destinataires)} destinataire(s).", "success")
    return redirect(url_for("main.dashboard"))
