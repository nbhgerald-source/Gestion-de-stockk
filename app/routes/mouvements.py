import csv
import io
from datetime import datetime

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.models import Depot, Mouvement, Produit, Tiers, TypeMouvement, TypeTiers
from app.services.mail_service import MailError, envoyer_alertes_stock
from app.services.permissions import (
    AccesRefuse,
    admin_requis,
    depots_modifiables,
    depots_visibles,
    peut_annuler_mouvement,
    verifier_ecriture_depot,
)
from app.services.stock_service import (
    StockError,
    annuler_mouvement,
    enregistrer_entree,
    enregistrer_sortie,
)

# Colonnes attendues dans le fichier CSV d'import du stock initial (delimiteur ";").
COLONNES_IMPORT_STOCK_INITIAL = [
    "code_produit",
    "depot_code",
    "quantite",
    "cout_unitaire",
    "date_entree",
    "numero_lot",
    "reference",
]


def _tiers_pour_entree():
    """Tiers utilisables comme origine d'une entree : fournisseurs + autres."""
    return (
        Tiers.query.filter(
            Tiers.actif.is_(True), Tiers.type_tiers.in_([TypeTiers.FOURNISSEUR, TypeTiers.AUTRE])
        )
        .order_by(Tiers.code.asc())
        .all()
    )


def _tiers_pour_sortie():
    """Tiers utilisables comme destinataire/consommateur d'une sortie : clients + autres."""
    return (
        Tiers.query.filter(
            Tiers.actif.is_(True), Tiers.type_tiers.in_([TypeTiers.CLIENT, TypeTiers.AUTRE])
        )
        .order_by(Tiers.code.asc())
        .all()
    )

bp = Blueprint("mouvements", __name__)


def _parse_date(valeur):
    if not valeur:
        return None
    return datetime.strptime(valeur, "%Y-%m-%d").date()


def _alerter_si_sous_seuil(produit):
    """Envoi best-effort (non bloquant) d'une alerte email si le produit est
    tombe au niveau ou en dessous de son stock de securite apres l'operation."""
    try:
        if produit.stock_securite and produit.quantite_stock <= produit.stock_securite:
            envoyer_alertes_stock([produit])
    except MailError:
        pass  # une panne d'envoi d'email ne doit jamais faire echouer un mouvement de stock


@bp.route("/")
@login_required
def liste():
    type_filtre = request.args.get("type", "")
    produit_id = request.args.get("produit_id", type=int)

    depots_lecture = depots_visibles(current_user)
    ids_depots_lecture = None if current_user.est_admin else [d.id for d in depots_lecture]

    requete = Mouvement.query
    if type_filtre:
        requete = requete.filter_by(type_mouvement=type_filtre)
    if produit_id:
        requete = requete.filter_by(produit_id=produit_id)
    if ids_depots_lecture is not None:
        requete = requete.filter(Mouvement.depot_id.in_(ids_depots_lecture or [-1]))

    tiers_id_filtre = request.args.get("tiers_id", type=int)
    if tiers_id_filtre:
        requete = requete.filter_by(tiers_id=tiers_id_filtre)

    mouvements = requete.order_by(Mouvement.date_mouvement.desc(), Mouvement.id.desc()).limit(200).all()
    produits = Produit.query.filter_by(actif=True).order_by(Produit.code.asc()).all()
    tous_tiers = Tiers.query.order_by(Tiers.code.asc()).all()

    # Identifiants du dernier mouvement enregistre pour chaque produit (tous
    # depots confondus) : seul ce mouvement peut etre annule, voir
    # stock_service.annuler_mouvement. On en deduit, pour l'utilisateur
    # courant, l'ensemble des mouvements affiches qu'il peut effectivement
    # annuler (niveau hierarchique + droit d'ecriture sur le depot concerne).
    derniers_ids = {
        produit_id_concerne
        for (produit_id_concerne,) in db.session.query(func.max(Mouvement.id)).group_by(Mouvement.produit_id)
    }
    mouvements_annulables = {
        m.id
        for m in mouvements
        if m.id in derniers_ids
        and not m.annule
        and not m.est_annulation
        and peut_annuler_mouvement(current_user, m)
    }

    return render_template(
        "mouvements/liste.html",
        mouvements=mouvements,
        produits=produits,
        types_mouvement=TypeMouvement.CHOIX,
        type_filtre=type_filtre,
        produit_id_filtre=produit_id,
        tous_tiers=tous_tiers,
        tiers_id_filtre=tiers_id_filtre,
        mouvements_annulables=mouvements_annulables,
    )


@bp.route("/<int:mouvement_id>/annuler", methods=["POST"])
@login_required
def annuler(mouvement_id):
    mouvement = Mouvement.query.get_or_404(mouvement_id)
    try:
        if not peut_annuler_mouvement(current_user, mouvement):
            raise AccesRefuse(
                "Annulation refusee : il faut un niveau hierarchique superieur a celui de "
                "l'auteur de ce mouvement, et un droit d'ecriture sur le depot concerne."
            )
        annuler_mouvement(mouvement, utilisateur=current_user.email)
        flash(f"Mouvement #{mouvement.id} annule avec succes.", "success")
    except AccesRefuse as exc:
        flash(str(exc), "danger")
    except StockError as exc:
        flash(str(exc), "danger")
    except Exception as exc:  # noqa: BLE001
        flash(f"Erreur lors de l'annulation : {exc}", "danger")
    return redirect(url_for("mouvements.liste"))


@bp.route("/entree", methods=["GET", "POST"])
@login_required
def entree():
    produits = Produit.query.filter_by(actif=True).order_by(Produit.code.asc()).all()
    depots = depots_modifiables(current_user)
    tiers_disponibles = _tiers_pour_entree()

    if request.method == "POST":
        try:
            produit = Produit.query.get_or_404(int(request.form["produit_id"]))
            depot_id = request.form.get("depot_id", type=int) or None
            tiers_id = request.form.get("tiers_id", type=int) or None
            verifier_ecriture_depot(current_user, depot_id)
            enregistrer_entree(
                produit,
                quantite=float(request.form["quantite"]),
                cout_unitaire=float(request.form["cout_unitaire"]),
                unite=request.form.get("unite", "GESTION"),
                numero_lot=request.form.get("numero_lot", "").strip() or None,
                date_entree=_parse_date(request.form.get("date_entree")),
                date_expiration=_parse_date(request.form.get("date_expiration")),
                depot_id=depot_id,
                tiers_id=tiers_id,
                reference=request.form.get("reference", "").strip() or None,
                motif=request.form.get("motif", "").strip() or None,
                utilisateur=current_user.email,
            )
            flash(f"Entree enregistree pour {produit.code}.", "success")
            return redirect(url_for("mouvements.liste"))
        except AccesRefuse as exc:
            flash(str(exc), "danger")
        except StockError as exc:
            flash(str(exc), "danger")
        except Exception as exc:  # noqa: BLE001
            flash(f"Erreur lors de l'enregistrement de l'entree : {exc}", "danger")

    return render_template(
        "mouvements/entree.html", produits=produits, depots=depots, tiers_disponibles=tiers_disponibles
    )


@bp.route("/sortie", methods=["GET", "POST"])
@login_required
def sortie():
    produits = Produit.query.filter_by(actif=True).order_by(Produit.code.asc()).all()
    depots = depots_modifiables(current_user)
    tiers_disponibles = _tiers_pour_sortie()

    if request.method == "POST":
        try:
            produit = Produit.query.get_or_404(int(request.form["produit_id"]))
            depot_id = request.form.get("depot_id", type=int) or None
            tiers_id = request.form.get("tiers_id", type=int) or None
            verifier_ecriture_depot(current_user, depot_id)
            enregistrer_sortie(
                produit,
                quantite=float(request.form["quantite"]),
                unite=request.form.get("unite", "GESTION"),
                depot_id=depot_id,
                tiers_id=tiers_id,
                reference=request.form.get("reference", "").strip() or None,
                motif=request.form.get("motif", "").strip() or None,
                utilisateur=current_user.email,
            )
            _alerter_si_sous_seuil(produit)
            flash(f"Sortie enregistree pour {produit.code}.", "success")
            return redirect(url_for("mouvements.liste"))
        except AccesRefuse as exc:
            flash(str(exc), "danger")
        except StockError as exc:
            flash(str(exc), "danger")
        except Exception as exc:  # noqa: BLE001
            flash(f"Erreur lors de l'enregistrement de la sortie : {exc}", "danger")

    return render_template(
        "mouvements/sortie.html", produits=produits, depots=depots, tiers_disponibles=tiers_disponibles
    )


@bp.route("/stock-initial/modele.csv")
@admin_requis
def modele_stock_initial():
    """Telecharge un modele CSV pour charger le stock initial (une ligne par
    lot/produit/depot). `code_produit` doit correspondre a un produit existant
    (Produits > Nouveau produit ou import en masse), `depot_code` a un depot
    existant (Parametres > Depots). `date_entree` est optionnelle (AAAA-MM-JJ,
    defaut = aujourd'hui) ; `numero_lot` et `reference` sont optionnels."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(COLONNES_IMPORT_STOCK_INITIAL)
    writer.writerow(["FAR-001", "PRINCIPAL", "500", "1.20", "2026-01-01", "", "Stock initial"])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=modele_import_stock_initial.csv"},
    )


@bp.route("/stock-initial/importer", methods=["GET", "POST"])
@admin_requis
def import_stock_initial():
    resultats = None

    if request.method == "POST":
        fichier = request.files.get("fichier")
        if not fichier or not fichier.filename:
            flash("Veuillez choisir un fichier CSV.", "danger")
            return render_template("mouvements/import_stock_initial.html", resultats=resultats)

        try:
            contenu = fichier.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Le fichier doit etre encode en UTF-8.", "danger")
            return render_template("mouvements/import_stock_initial.html", resultats=resultats)

        lecteur = csv.DictReader(io.StringIO(contenu), delimiter=";")
        produits_par_code = {p.code.upper(): p for p in Produit.query.all()}
        depots_par_code = {d.code.upper(): d for d in Depot.query.all()}

        # 1ere passe : validation complete avant toute ecriture (import tout-ou-rien).
        lignes_valides = []
        erreurs = []
        for numero_ligne, ligne in enumerate(lecteur, start=2):  # ligne 1 = entete
            try:
                code_produit = (ligne.get("code_produit") or "").strip().upper()
                code_depot = (ligne.get("depot_code") or "").strip().upper()
                produit = produits_par_code.get(code_produit)
                depot = depots_par_code.get(code_depot)
                if not produit:
                    raise ValueError(f"produit inconnu : {code_produit!r}")
                if not depot:
                    raise ValueError(f"depot inconnu : {code_depot!r}")

                quantite = float(ligne.get("quantite") or 0)
                cout_unitaire = float(ligne.get("cout_unitaire") or 0)
                if quantite <= 0:
                    raise ValueError("quantite doit etre superieure a zero")
                if cout_unitaire < 0:
                    raise ValueError("cout_unitaire doit etre positif ou nul")

                date_entree = _parse_date((ligne.get("date_entree") or "").strip() or None)

                lignes_valides.append(
                    {
                        "produit": produit,
                        "depot": depot,
                        "quantite": quantite,
                        "cout_unitaire": cout_unitaire,
                        "date_entree": date_entree,
                        "numero_lot": (ligne.get("numero_lot") or "").strip() or None,
                        "reference": (ligne.get("reference") or "").strip() or None,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                erreurs.append(f"Ligne {numero_ligne} : {exc}")

        if erreurs:
            resultats = {"importes": [], "erreurs": erreurs}
            flash(
                f"Import annule : {len(erreurs)} erreur(s) detectee(s). Aucune entree n'a ete enregistree.",
                "danger",
            )
            return render_template("mouvements/import_stock_initial.html", resultats=resultats)

        importes = []
        for donnee in lignes_valides:
            enregistrer_entree(
                donnee["produit"],
                quantite=donnee["quantite"],
                cout_unitaire=donnee["cout_unitaire"],
                unite="GESTION",
                numero_lot=donnee["numero_lot"],
                date_entree=donnee["date_entree"],
                depot_id=donnee["depot"].id,
                reference=donnee["reference"],
                motif="Stock initial (import CSV)",
                utilisateur=current_user.email,
            )
            importes.append(f"{donnee['produit'].code} / {donnee['depot'].code}")

        resultats = {"importes": importes, "erreurs": []}
        flash(f"{len(importes)} entree(s) de stock initial enregistree(s) avec succes.", "success")

    return render_template("mouvements/import_stock_initial.html", resultats=resultats)
