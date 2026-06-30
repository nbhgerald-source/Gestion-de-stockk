"""
Notifications par email des alertes de stock de securite.

Si MAIL_SERVEUR n'est pas configure (variables d'environnement absentes),
les emails ne sont pas envoyes : le contenu est simplement affiche dans la
console du serveur (mode "dry run"), ce qui permet de developper/tester sans
serveur SMTP. En production, definir MAIL_SERVEUR / MAIL_PORT /
MAIL_UTILISATEUR / MAIL_MOT_DE_PASSE / MAIL_EXPEDITEUR pour un envoi reel.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app

from app.models import Utilisateur


class MailError(Exception):
    """Erreur lors de l'envoi d'un email."""


def _construire_corps_alertes(alertes):
    lignes = [
        f"- {p.code} {p.designation} : stock {p.quantite_stock} {p.unite_gestion.code} "
        f"(seuil de securite {p.stock_securite} {p.unite_gestion.code})"
        for p in alertes
    ]
    corps = (
        "Les produits suivants sont au niveau ou en dessous de leur stock de securite :\n\n"
        + "\n".join(lignes)
        + "\n\nMerci de planifier un reapprovisionnement.\n"
    )
    return corps


def _envoyer(destinataires, sujet, corps):
    serveur = current_app.config.get("MAIL_SERVEUR")
    expediteur = current_app.config.get("MAIL_EXPEDITEUR", "stock@local")

    if not serveur:
        # Mode "dry run" : pas de serveur SMTP configure -> on logge seulement.
        print(f"[mail_service] (dry run, MAIL_SERVEUR non configure) Sujet: {sujet}")
        print(f"[mail_service] Destinataires : {', '.join(destinataires)}")
        print(corps)
        return False

    message = MIMEMultipart()
    message["From"] = expediteur
    message["To"] = ", ".join(destinataires)
    message["Subject"] = sujet
    message.attach(MIMEText(corps, "plain", "utf-8"))

    port = current_app.config.get("MAIL_PORT", 587)
    utilisateur = current_app.config.get("MAIL_UTILISATEUR", "")
    mot_de_passe = current_app.config.get("MAIL_MOT_DE_PASSE", "")
    use_tls = current_app.config.get("MAIL_USE_TLS", True)

    try:
        with smtplib.SMTP(serveur, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls()
            if utilisateur:
                smtp.login(utilisateur, mot_de_passe)
            smtp.sendmail(expediteur, destinataires, message.as_string())
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"Echec de l'envoi de l'email : {exc}") from exc

    return True


def envoyer_alertes_stock(alertes):
    """Envoie un email recapitulatif des alertes de stock de securite a tous
    les utilisateurs actifs ayant `recevoir_alertes_email = True`.

    Retourne (envoye: bool, destinataires: list[str]) ; envoye=False si
    aucun destinataire n'est inscrit ou si aucune alerte n'est active."""
    if not alertes:
        return False, []

    destinataires = [
        u.email
        for u in Utilisateur.query.filter_by(actif=True, recevoir_alertes_email=True).all()
    ]
    if not destinataires:
        return False, []

    sujet = f"[Gestion de Stock] {len(alertes)} produit(s) sous le seuil de securite"
    corps = _construire_corps_alertes(alertes)
    _envoyer(destinataires, sujet, corps)
    return True, destinataires
