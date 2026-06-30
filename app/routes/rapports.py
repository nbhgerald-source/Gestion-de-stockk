import csv
import io
from datetime import date, datetime

from flask import Blueprint, Response, abort, render_template, request
from flask_login import current_user, login_required

from app.models import TypeProduit
from app.services.permissions import depots_visibles
from app.services.report_service import PERIODES, generer_rapport_stock, rapport_par_tiers

bp = Blueprint("rapports", __name__)


def _params():
    type_periode = request.args.get("type_periode", "MOIS")
    date_str = request.args.get("date_reference", "")
    try:
        date_reference = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    except ValueError:
        date_reference = date.today()
    type_produit = request.args.get("type_produit", "") or None
    depot_param = request.args.get("depot_id", "") or ""
    return type_periode, date_reference, type_produit, depot_param


def _resoudre_depot_ids(depot_param, depots_autorises):
    """Determine la liste depot_ids a transmettre a generer_rapport_stock,
    en fonction du depot demande (`depot_param`) et des depots auxquels
    l'utilisateur courant a un acces en lecture (`depots_autorises`).

    - depot_param == "" (Consolide) :
        - admin -> None (rapport consolide rapide, tous depots)
        - utilisateur standard -> liste de ses depots autorises (consolide
          partiel, restreint a ce qu'il a le droit de voir)
    - depot_param == "<id>" : ce depot precis, si autorise (sinon 403)."""
    ids_autorises = {d.id for d in depots_autorises}

    if not depot_param:
        if current_user.est_admin:
            return None
        return list(ids_autorises) if ids_autorises else [-1]

    try:
        depot_id = int(depot_param)
    except ValueError:
        abort(404)

    if depot_id not in ids_autorises:
        abort(403)

    return [depot_id]


@bp.route("/")
@login_required
def index():
    type_periode, date_reference, type_produit, depot_param = _params()
    depots_autorises = depots_visibles(current_user)
    depot_ids = _resoudre_depot_ids(depot_param, depots_autorises)

    rapport = generer_rapport_stock(type_periode, date_reference, type_produit, depot_ids=depot_ids)
    return render_template(
        "rapports/index.html",
        rapport=rapport,
        periodes=PERIODES,
        types_produit=TypeProduit.CHOIX,
        type_periode=type_periode,
        date_reference=date_reference.isoformat(),
        type_produit=type_produit or "",
        depots=depots_autorises,
        depot_id=depot_param,
    )


@bp.route("/par-tiers")
@login_required
def par_tiers():
    type_periode, date_reference, _type_produit, depot_param = _params()
    depots_autorises = depots_visibles(current_user)
    depot_ids = _resoudre_depot_ids(depot_param, depots_autorises)

    rapport = rapport_par_tiers(type_periode, date_reference, depot_ids=depot_ids)
    return render_template(
        "rapports/par_tiers.html",
        rapport=rapport,
        periodes=PERIODES,
        type_periode=type_periode,
        date_reference=date_reference.isoformat(),
        depots=depots_autorises,
        depot_id=depot_param,
    )


@bp.route("/export.csv")
@login_required
def export_csv():
    type_periode, date_reference, type_produit, depot_param = _params()
    depots_autorises = depots_visibles(current_user)
    depot_ids = _resoudre_depot_ids(depot_param, depots_autorises)

    rapport = generer_rapport_stock(type_periode, date_reference, type_produit, depot_ids=depot_ids)

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "Code", "Designation", "Type",
            "Stock initial (qte)", "Stock initial (valeur)",
            "Entrees (qte)", "Entrees (valeur)",
            "Sorties (qte)", "Sorties (valeur)",
            "Stock final (qte)", "Stock final (valeur)",
        ]
    )
    for ligne in rapport["lignes"]:
        p = ligne["produit"]
        writer.writerow(
            [
                p.code,
                p.designation,
                TypeProduit.libelle(p.type_produit),
                ligne["stock_initial_qte"], ligne["stock_initial_valeur"],
                ligne["entrees_qte"], ligne["entrees_valeur"],
                ligne["sorties_qte"], ligne["sorties_valeur"],
                ligne["stock_final_qte"], ligne["stock_final_valeur"],
            ]
        )

    suffixe_depot = f"_depot{depot_param}" if depot_param else "_consolide"
    nom_fichier = f"rapport_stock_{type_periode.lower()}_{date_reference.isoformat()}{suffixe_depot}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nom_fichier}"},
    )
