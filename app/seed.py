"""Donnees de base inserees automatiquement au demarrage si la base est vide :
quelques unites de mesure courantes, un depot principal, et un compte
administrateur par defaut (a utiliser uniquement pour la premiere connexion,
puis a changer immediatement)."""

import os

from app.extensions import db
from app.models import Depot, UniteMesure, Utilisateur

UNITES_BASE = [
    ("KG", "Kilogramme"),
    ("G", "Gramme"),
    ("L", "Litre"),
    ("PCE", "Piece"),
    ("CARTON", "Carton"),
    ("SAC", "Sac"),
    ("PALETTE", "Palette"),
    ("M", "Metre"),
]

ADMIN_EMAIL_DEFAUT = os.environ.get("ADMIN_EMAIL_DEFAUT", "admin@stock.local")
ADMIN_MOT_DE_PASSE_DEFAUT = os.environ.get("ADMIN_MOTDEPASSE_DEFAUT", "admin123")


def inserer_donnees_de_base():
    if UniteMesure.query.count() == 0:
        for code, libelle in UNITES_BASE:
            db.session.add(UniteMesure(code=code, libelle=libelle))

    if Depot.query.count() == 0:
        db.session.add(Depot(code="PRINCIPAL", nom="Depot principal"))

    if Utilisateur.query.count() == 0:
        admin = Utilisateur(
            nom="Administrateur",
            email=ADMIN_EMAIL_DEFAUT,
            est_admin=True,
            actif=True,
        )
        admin.definir_mot_de_passe(ADMIN_MOT_DE_PASSE_DEFAUT)
        db.session.add(admin)
        print(
            "\n*** Compte administrateur cree automatiquement ***\n"
            f"    Email : {ADMIN_EMAIL_DEFAUT}\n"
            f"    Mot de passe : {ADMIN_MOT_DE_PASSE_DEFAUT}\n"
            "    Merci de changer ce mot de passe dans Utilisateurs > Modifier.\n"
        )

    db.session.commit()
