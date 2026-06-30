from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.models import Utilisateur

bp = Blueprint("auth", __name__)


@bp.route("/connexion", methods=["GET", "POST"])
def connexion():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        mot_de_passe = request.form.get("mot_de_passe", "")
        utilisateur = Utilisateur.query.filter_by(email=email).first()

        if (
            utilisateur
            and utilisateur.actif
            and utilisateur.verifier_mot_de_passe(mot_de_passe)
        ):
            login_user(utilisateur)
            suite = request.args.get("next")
            return redirect(suite or url_for("main.dashboard"))

        flash("Email ou mot de passe incorrect.", "danger")

    return render_template("auth/connexion.html")


@bp.route("/deconnexion")
@login_required
def deconnexion():
    logout_user()
    flash("Vous avez ete deconnecte.", "info")
    return redirect(url_for("auth.connexion"))
