import csv
import io

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Lot, Mouvement, Produit, TypeProduit, UniteMesure
from app.services.permissions import admin_requis

bp = Blueprint("produits", __name__)

# Colonnes attendues dans le fichier CSV d'import des produits (delimiteur ";").
COLONNES_IMPORT_PRODUITS = [
    "code",
    "designation",
    "type_produit",
    "unite_achat_code",
    "unite_gestion_code",
    "facteur_conversion",
    "libelle_colisage",
    "stock_securite",
]


@bp.route("/")
@login_required
def liste():
    type_filtre = request.args.get("type", "")
    requete = Produit.query
    if type_filtre:
        requete = requete.filter_by(type_produit=type_filtre)
    produits = requete.order_by(Produit.code.asc()).all()
    return render_template(
        "produits/liste.html",
        produits=produits,
        types_produit=TypeProduit.CHOIX,
        type_filtre=type_filtre,
    )


@bp.route("/<int:produit_id>")
@login_required
def detail(produit_id):
    produit = Produit.query.get_or_404(produit_id)
    lots = (
        Lot.query.filter_by(produit_id=produit_id)
        .order_by(Lot.date_entree.asc(), Lot.id.asc())
        .all()
    )
    mouvements = (
        Mouvement.query.filter_by(produit_id=produit_id)
        .order_by(Mouvement.date_mouvement.desc(), Mouvement.id.desc())
        .limit(50)
        .all()
    )
    return render_template("produits/detail.html", produit=produit, lots=lots, mouvements=mouvements)


def _unites():
    return UniteMesure.query.order_by(UniteMesure.code.asc()).all()


@bp.route("/nouveau", methods=["GET", "POST"])
@admin_requis
def nouveau():
    if request.method == "POST":
        try:
            produit = Produit(
                code=request.form["code"].strip().upper(),
                designation=request.form["designation"].strip(),
                type_produit=request.form["type_produit"],
                unite_achat_id=int(request.form["unite_achat_id"]),
                unite_gestion_id=int(request.form["unite_gestion_id"]),
                facteur_conversion=float(request.form.get("facteur_conversion") or 1.0),
                libelle_colisage=request.form.get("libelle_colisage", "").strip() or None,
                stock_securite=float(request.form.get("stock_securite") or 0.0),
            )
            db.session.add(produit)
            db.session.commit()
            flash(f"Produit {produit.code} cree avec succes.", "success")
            return redirect(url_for("produits.detail", produit_id=produit.id))
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            flash(f"Erreur lors de la creation du produit : {exc}", "danger")

    return render_template(
        "produits/form.html",
        produit=None,
        unites=_unites(),
        types_produit=TypeProduit.CHOIX,
    )


@bp.route("/<int:produit_id>/modifier", methods=["GET", "POST"])
@admin_requis
def modifier(produit_id):
    produit = Produit.query.get_or_404(produit_id)

    if request.method == "POST":
        try:
            produit.designation = request.form["designation"].strip()
            produit.type_produit = request.form["type_produit"]
            produit.unite_achat_id = int(request.form["unite_achat_id"])
            produit.unite_gestion_id = int(request.form["unite_gestion_id"])
            produit.facteur_conversion = float(request.form.get("facteur_conversion") or 1.0)
            produit.libelle_colisage = request.form.get("libelle_colisage", "").strip() or None
            produit.stock_securite = float(request.form.get("stock_securite") or 0.0)
            produit.actif = bool(request.form.get("actif"))
            db.session.commit()
            flash(f"Produit {produit.code} mis a jour.", "success")
            return redirect(url_for("produits.detail", produit_id=produit.id))
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            flash(f"Erreur lors de la mise a jour : {exc}", "danger")

    return render_template(
        "produits/form.html",
        produit=produit,
        unites=_unites(),
        types_produit=TypeProduit.CHOIX,
    )


@bp.route("/modele-import.csv")
@admin_requis
def modele_import():
    """Telecharge un modele CSV (avec un exemple) pour charger l'ensemble des
    articles en masse. `type_produit` doit etre un des codes :
    MATIERE_PREMIERE, ACCESSOIRE, SEMI_FINI, RESIDUEL, PRODUIT_FINI.
    `unite_achat_code` / `unite_gestion_code` doivent correspondre a des codes
    d'unites de mesure existants (Parametres > Unites de mesure)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(COLONNES_IMPORT_PRODUITS)
    writer.writerow(
        [
            "FAR-001", "Farine de ble", "MATIERE_PREMIERE", "SAC", "KG", "25", "Sac de 25 kg", "100",
        ]
    )
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=modele_import_produits.csv"},
    )


@bp.route("/importer", methods=["GET", "POST"])
@admin_requis
def import_produits():
    resultats = None

    if request.method == "POST":
        fichier = request.files.get("fichier")
        if not fichier or not fichier.filename:
            flash("Veuillez choisir un fichier CSV.", "danger")
            return render_template("produits/import.html", resultats=resultats)

        try:
            contenu = fichier.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Le fichier doit etre encode en UTF-8.", "danger")
            return render_template("produits/import.html", resultats=resultats)

        lecteur = csv.DictReader(io.StringIO(contenu), delimiter=";")
        unites_par_code = {u.code.upper(): u for u in UniteMesure.query.all()}
        types_valides = {code for code, _ in TypeProduit.CHOIX}

        crees, erreurs = [], []
        for numero_ligne, ligne in enumerate(lecteur, start=2):  # ligne 1 = entete
            try:
                code = (ligne.get("code") or "").strip().upper()
                if not code:
                    raise ValueError("code manquant")
                if Produit.query.filter_by(code=code).first():
                    raise ValueError(f"le produit {code} existe deja")

                type_produit = (ligne.get("type_produit") or "").strip().upper()
                if type_produit not in types_valides:
                    raise ValueError(f"type_produit invalide : {type_produit!r}")

                code_achat = (ligne.get("unite_achat_code") or "").strip().upper()
                code_gestion = (ligne.get("unite_gestion_code") or "").strip().upper()
                unite_achat = unites_par_code.get(code_achat)
                unite_gestion = unites_par_code.get(code_gestion)
                if not unite_achat:
                    raise ValueError(f"unite d'achat inconnue : {code_achat!r}")
                if not unite_gestion:
                    raise ValueError(f"unite de gestion inconnue : {code_gestion!r}")

                produit = Produit(
                    code=code,
                    designation=(ligne.get("designation") or "").strip(),
                    type_produit=type_produit,
                    unite_achat_id=unite_achat.id,
                    unite_gestion_id=unite_gestion.id,
                    facteur_conversion=float(ligne.get("facteur_conversion") or 1.0),
                    libelle_colisage=(ligne.get("libelle_colisage") or "").strip() or None,
                    stock_securite=float(ligne.get("stock_securite") or 0.0),
                )
                if not produit.designation:
                    raise ValueError("designation manquante")

                db.session.add(produit)
                db.session.flush()
                crees.append(produit.code)
            except Exception as exc:  # noqa: BLE001
                erreurs.append(f"Ligne {numero_ligne} : {exc}")

        if erreurs:
            db.session.rollback()
            resultats = {"crees": [], "erreurs": erreurs}
            flash(
                f"Import annule : {len(erreurs)} erreur(s) detectee(s). Aucun produit n'a ete cree.",
                "danger",
            )
        else:
            db.session.commit()
            resultats = {"crees": crees, "erreurs": []}
            flash(f"{len(crees)} produit(s) importe(s) avec succes.", "success")

    return render_template("produits/import.html", resultats=resultats)
