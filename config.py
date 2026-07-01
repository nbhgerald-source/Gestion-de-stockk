import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Configuration de l'application.

    En local (par defaut) : base SQLite, aucune installation supplementaire requise.
    En production / cloud : definir la variable d'environnement DATABASE_URL,
    par exemple une base PostgreSQL :
        DATABASE_URL=postgresql://utilisateur:motdepasse@hote:5432/nom_base
    """

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-moi-en-production")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "stock.db")
    )
    # Render/Heroku fournissent parfois une URL qui commence par postgres://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Options du moteur SQLAlchemy — essentielles pour PostgreSQL sur Render :
    #   pool_pre_ping   : teste la connexion avant usage, reconnecte si morte (SSL stale)
    #   pool_recycle    : recycle les connexions toutes les 5 min (évite les déconnexions SSL)
    #   connect_args    : force SSL requis pour PostgreSQL (ignoré par SQLite)
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    # Nombre de decimales utilisees pour l'arrondi des couts/valeurs monetaires
    DECIMALES_VALEUR = 2
    # Nombre de decimales utilisees pour l'arrondi des quantites
    DECIMALES_QUANTITE = 3

    # --- Notifications email (alertes de stock de securite) ---
    # Definir ces variables d'environnement pour activer l'envoi reel ; sinon
    # le service de mail se contente de logguer dans la console (mode "dry run").
    MAIL_SERVEUR = os.environ.get("MAIL_SERVEUR", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_UTILISATEUR = os.environ.get("MAIL_UTILISATEUR", "")
    MAIL_MOT_DE_PASSE = os.environ.get("MAIL_MOT_DE_PASSE", "")
    MAIL_EXPEDITEUR = os.environ.get("MAIL_EXPEDITEUR", "stock@local")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") not in ("0", "false", "False")
