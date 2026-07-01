from flask import Flask, Response, flash, redirect, request, url_for
from flask_login import current_user

from app.extensions import db, login_manager
from app.models import TypeProduit, Utilisateur


def create_app(config_object="config.Config"):
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.connexion"
    login_manager.login_message = "Veuillez vous connecter pour acceder a cette page."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def charger_utilisateur(user_id):
        try:
            return Utilisateur.query.get(int(user_id))
        except Exception:
            # Connexion SSL perdue / erreur DB transitoire — on retourne None
            # (utilisateur non authentifié) plutôt que de lever une exception 500.
            db.session.rollback()
            return None

    from app.routes.auth import bp as auth_bp
    from app.routes.main import bp as main_bp
    from app.routes.produits import bp as produits_bp
    from app.routes.parametres import bp as parametres_bp
    from app.routes.mouvements import bp as mouvements_bp
    from app.routes.rapports import bp as rapports_bp
    from app.routes.utilisateurs import bp as utilisateurs_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(produits_bp, url_prefix="/produits")
    app.register_blueprint(parametres_bp, url_prefix="/parametres")
    app.register_blueprint(mouvements_bp, url_prefix="/mouvements")
    app.register_blueprint(rapports_bp, url_prefix="/rapports")
    app.register_blueprint(utilisateurs_bp, url_prefix="/utilisateurs")

    # Endpoint léger pour le health check Render — pas de DB, retour immédiat.
    @app.route("/health")
    def health():
        return Response("ok", status=200, mimetype="text/plain")

    # Toute l'application necessite une connexion, a l'exception des routes
    # d'authentification et des fichiers statiques.
    @app.before_request
    def exiger_connexion():
        endpoints_publics = {"auth.connexion", "health", "static"}
        if request.endpoint in endpoints_publics:
            return None
        if not current_user.is_authenticated:
            return redirect(url_for("auth.connexion", next=request.path))
        if not current_user.actif:
            flash("Votre compte a ete desactive. Contactez un administrateur.", "danger")
            return redirect(url_for("auth.connexion"))
        return None

    @app.template_filter("fmt_qte")
    def fmt_qte(valeur):
        try:
            return f"{float(valeur):,.3f}".replace(",", " ")
        except (TypeError, ValueError):
            return valeur

    @app.template_filter("fmt_montant")
    def fmt_montant(valeur):
        try:
            return f"{float(valeur):,.2f}".replace(",", " ")
        except (TypeError, ValueError):
            return valeur

    @app.template_filter("libelle_type")
    def libelle_type(code):
        return TypeProduit.libelle(code)

    @app.context_processor
    def injecter_droits_depots():
        """Expose un indicateur simple `a_un_depot_en_ecriture` aux templates,
        pour masquer les liens Entree/Sortie quand l'utilisateur n'a aucun
        depot ou les droits d'ecriture necessaires."""
        if not current_user.is_authenticated:
            return {}
        if current_user.est_admin:
            return {"a_un_depot_en_ecriture": True}
        ids = current_user.depots_ecriture_ids or []
        return {"a_un_depot_en_ecriture": bool(ids)}

    with app.app_context():
        db.create_all()
        from app.seed import inserer_donnees_de_base
        inserer_donnees_de_base()

    return app
