"""
Modeles de donnees de l'application de gestion de stock.

Principes de gestion implementes :
- Unite d'achat / unite de gestion de stock + facteur de conversion (colisage).
- Gestion de lots avec consommation FIFO (Premier Entre, Premier Sorti) a la sortie.
- Valorisation du stock au Cout Unitaire Moyen Pondere (CUMP / PMP) :
    * Le PMP est recalcule a chaque ENTREE :
          PMP_apres = (Qte_stock_avant * PMP_avant + Qte_entree * CoutUnitaire_entree)
                      / (Qte_stock_avant + Qte_entree)
    * A la SORTIE, le PMP ne change pas ; la valeur sortie = Qte_sortie * PMP_courant.
    * Les lots, eux, sont consommes dans l'ordre FIFO (date d'entree la plus ancienne
      en premier) afin de respecter la regle de gestion physique du stock, tout en
      gardant une valorisation comptable unique et lissee (PMP) par produit.
- Stock de securite par produit -> permet de generer des alertes (rupture / sous le seuil).
"""

from datetime import datetime, date

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


# ---------------------------------------------------------------------------
# Enumerations (stockees comme chaines pour rester simples et lisibles en base)
# ---------------------------------------------------------------------------

class TypeProduit:
    MATIERE_PREMIERE = "MATIERE_PREMIERE"
    ACCESSOIRE = "ACCESSOIRE"
    SEMI_FINI = "SEMI_FINI"
    RESIDUEL = "RESIDUEL"
    PRODUIT_FINI = "PRODUIT_FINI"

    CHOIX = [
        (MATIERE_PREMIERE, "Matiere premiere"),
        (ACCESSOIRE, "Accessoire"),
        (SEMI_FINI, "Produit semi-fini"),
        (RESIDUEL, "Produit residuel"),
        (PRODUIT_FINI, "Produit fini"),
    ]

    @classmethod
    def libelle(cls, code):
        return dict(cls.CHOIX).get(code, code)


class TypeMouvement:
    ENTREE = "ENTREE"
    SORTIE = "SORTIE"
    AJUSTEMENT_POSITIF = "AJUSTEMENT_POSITIF"
    AJUSTEMENT_NEGATIF = "AJUSTEMENT_NEGATIF"
    ANNULATION = "ANNULATION"

    CHOIX = [
        (ENTREE, "Entree"),
        (SORTIE, "Sortie"),
        (AJUSTEMENT_POSITIF, "Ajustement positif"),
        (AJUSTEMENT_NEGATIF, "Ajustement negatif"),
        (ANNULATION, "Annulation"),
    ]

    @classmethod
    def libelle(cls, code):
        return dict(cls.CHOIX).get(code, code)


class NiveauUtilisateur:
    """Hierarchie utilisee pour autoriser l'annulation d'un mouvement :
    seul un utilisateur de niveau STRICTEMENT SUPERIEUR a celui de l'auteur
    du mouvement peut l'annuler (ex: un Superviseur peut annuler un mouvement
    saisi par un Standard ; un Standard ne peut jamais annuler, meme ses
    propres mouvements)."""

    STANDARD = 1
    SUPERVISEUR = 2
    ADMINISTRATEUR = 3

    CHOIX = [
        (STANDARD, "Standard"),
        (SUPERVISEUR, "Superviseur"),
        (ADMINISTRATEUR, "Administrateur"),
    ]

    @classmethod
    def libelle(cls, valeur):
        return dict(cls.CHOIX).get(valeur, str(valeur))


# ---------------------------------------------------------------------------
# Unite de mesure
# ---------------------------------------------------------------------------

class UniteMesure(db.Model):
    __tablename__ = "unite_mesure"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)  # ex: KG, PCE, CARTON
    libelle = db.Column(db.String(100), nullable=False)  # ex: Kilogramme, Piece, Carton

    def __repr__(self):
        return f"<UniteMesure {self.code}>"


# ---------------------------------------------------------------------------
# Depot (extensible pour le multi-site ; un depot "Principal" est cree par defaut)
# ---------------------------------------------------------------------------

class Depot(db.Model):
    __tablename__ = "depot"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    nom = db.Column(db.String(100), nullable=False)
    actif = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<Depot {self.code}>"


# ---------------------------------------------------------------------------
# Produit
# ---------------------------------------------------------------------------

class Produit(db.Model):
    __tablename__ = "produit"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    designation = db.Column(db.String(200), nullable=False)
    type_produit = db.Column(db.String(30), nullable=False, default=TypeProduit.MATIERE_PREMIERE)

    # Unite dans laquelle le produit est achete (ex: Carton, Palette, Sac...)
    unite_achat_id = db.Column(db.Integer, db.ForeignKey("unite_mesure.id"), nullable=False)
    unite_achat = db.relationship("UniteMesure", foreign_keys=[unite_achat_id])

    # Unite dans laquelle le stock est gere/suivi (ex: Kg, Piece, Litre...)
    unite_gestion_id = db.Column(db.Integer, db.ForeignKey("unite_mesure.id"), nullable=False)
    unite_gestion = db.relationship("UniteMesure", foreign_keys=[unite_gestion_id])

    # Colisage / facteur de conversion : nombre d'unites de gestion contenues
    # dans une unite d'achat. Ex : 1 carton (unite d'achat) = 24 pieces (unite de gestion)
    # => facteur_conversion = 24. Si unite_achat == unite_gestion, facteur = 1.
    facteur_conversion = db.Column(db.Float, nullable=False, default=1.0)
    libelle_colisage = db.Column(db.String(100))  # ex: "Carton de 24 unites"

    # Stock de securite, exprime en unite de GESTION
    stock_securite = db.Column(db.Float, nullable=False, default=0.0)

    # Champs caches, mis a jour exclusivement par app.services.stock_service
    # (a ne jamais modifier manuellement ailleurs dans le code).
    quantite_stock = db.Column(db.Float, nullable=False, default=0.0)
    pmp = db.Column(db.Float, nullable=False, default=0.0)  # cout unitaire moyen pondere

    actif = db.Column(db.Boolean, default=True, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    lots = db.relationship("Lot", backref="produit", lazy="dynamic", cascade="all, delete-orphan")
    mouvements = db.relationship(
        "Mouvement", backref="produit", lazy="dynamic", cascade="all, delete-orphan"
    )

    # -- Proprietes utilitaires -------------------------------------------------

    @property
    def valeur_stock(self):
        """Valeur totale du stock courant, valorisee au PMP."""
        return round((self.quantite_stock or 0.0) * (self.pmp or 0.0), 2)

    @property
    def en_alerte(self):
        """Vrai si le stock est descendu au niveau (ou sous) le seuil de securite."""
        return self.stock_securite > 0 and self.quantite_stock <= self.stock_securite

    @property
    def en_rupture(self):
        return self.quantite_stock <= 0

    def __repr__(self):
        return f"<Produit {self.code} - {self.designation}>"


# ---------------------------------------------------------------------------
# Lot (gestion de lots, support de la methode FIFO)
# ---------------------------------------------------------------------------

class Lot(db.Model):
    __tablename__ = "lot"

    id = db.Column(db.Integer, primary_key=True)
    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    depot_id = db.Column(db.Integer, db.ForeignKey("depot.id"), nullable=True)
    depot = db.relationship("Depot")

    numero_lot = db.Column(db.String(50), nullable=False)

    # Date d'entree en stock : c'est elle qui determine l'ordre FIFO
    # (le lot avec la date la plus ancienne est consomme en premier).
    date_entree = db.Column(db.Date, nullable=False, default=date.today)
    date_expiration = db.Column(db.Date, nullable=True)

    quantite_initiale = db.Column(db.Float, nullable=False)
    quantite_restante = db.Column(db.Float, nullable=False)

    # Cout d'achat unitaire (en unite de GESTION) de ce lot specifique.
    # Conserve pour la tracabilite et les couts de remplacement, meme si la
    # valorisation comptable du stock utilise le PMP du produit (et non ce cout de lot).
    cout_unitaire_achat = db.Column(db.Float, nullable=False, default=0.0)

    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def epuise(self):
        return self.quantite_restante <= 0

    def __repr__(self):
        return f"<Lot {self.numero_lot} produit={self.produit_id}>"


# ---------------------------------------------------------------------------
# Tiers (fournisseurs / clients / consommateurs) : origine d'une entree,
# destinataire d'une sortie. Permet d'analyser les mouvements par partenaire.
# ---------------------------------------------------------------------------

class TypeTiers:
    FOURNISSEUR = "FOURNISSEUR"
    CLIENT = "CLIENT"
    AUTRE = "AUTRE"

    CHOIX = [
        (FOURNISSEUR, "Fournisseur"),
        (CLIENT, "Client / consommateur"),
        (AUTRE, "Autre"),
    ]

    @classmethod
    def libelle(cls, code):
        return dict(cls.CHOIX).get(code, code)


class Tiers(db.Model):
    """Partenaire externe ou interne : fournisseur (origine d'une entree),
    client/consommateur (destinataire d'une sortie), ou autre (service interne,
    atelier de production...)."""

    __tablename__ = "tiers"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    nom = db.Column(db.String(150), nullable=False)
    type_tiers = db.Column(db.String(20), nullable=False, default=TypeTiers.AUTRE)
    actif = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<Tiers {self.code} - {self.nom}>"


# ---------------------------------------------------------------------------
# Mouvement de stock (entree / sortie / ajustement)
# ---------------------------------------------------------------------------

class Mouvement(db.Model):
    __tablename__ = "mouvement"

    id = db.Column(db.Integer, primary_key=True)
    type_mouvement = db.Column(db.String(30), nullable=False)

    produit_id = db.Column(db.Integer, db.ForeignKey("produit.id"), nullable=False)
    depot_id = db.Column(db.Integer, db.ForeignKey("depot.id"), nullable=True)
    depot = db.relationship("Depot")

    # Origine (fournisseur) pour une entree, destinataire/consommateur (client,
    # service, atelier...) pour une sortie. Permet d'analyser les mouvements
    # par partenaire (qui livre, qui consomme).
    tiers_id = db.Column(db.Integer, db.ForeignKey("tiers.id"), nullable=True)
    tiers = db.relationship("Tiers")

    date_mouvement = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Quantite du mouvement, toujours normalisee en unite de GESTION (positive)
    quantite = db.Column(db.Float, nullable=False)

    # Cout unitaire applique a ce mouvement (unite de gestion) :
    #  - ENTREE : cout d'achat unitaire reel de l'entree
    #  - SORTIE / AJUSTEMENT : PMP du produit au moment du mouvement
    cout_unitaire = db.Column(db.Float, nullable=False, default=0.0)
    valeur = db.Column(db.Float, nullable=False, default=0.0)  # quantite * cout_unitaire

    # Etat du produit immediatement APRES ce mouvement (pour audit & rapports rapides)
    pmp_apres = db.Column(db.Float, nullable=False, default=0.0)
    stock_apres = db.Column(db.Float, nullable=False, default=0.0)

    reference = db.Column(db.String(100))  # ex: n° bon de commande / livraison
    motif = db.Column(db.String(255))
    utilisateur = db.Column(db.String(100), default="systeme")

    # -- Annulation -----------------------------------------------------
    # `annule` : ce mouvement original a ete annule (son effet sur le stock a
    # ete neutralise par un mouvement compensatoire, cree ci-dessous).
    # `est_annulation` : ce mouvement EST le mouvement compensatoire (cree
    # automatiquement par stock_service.annuler_mouvement), il ne peut donc
    # pas etre annule lui-meme.
    annule = db.Column(db.Boolean, default=False, nullable=False)
    est_annulation = db.Column(db.Boolean, default=False, nullable=False)
    mouvement_origine_id = db.Column(db.Integer, db.ForeignKey("mouvement.id"), nullable=True)
    annule_par = db.Column(db.String(100), nullable=True)
    date_annulation = db.Column(db.DateTime, nullable=True)

    mouvement_origine = db.relationship(
        "Mouvement", remote_side=[id], backref="annulations"
    )

    lignes_lot = db.relationship(
        "MouvementLot", backref="mouvement", lazy="dynamic", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Mouvement {self.type_mouvement} produit={self.produit_id} qte={self.quantite}>"


class MouvementLot(db.Model):
    """Table d'association : quelle(s) quantite(s) de quel(s) lot(s) ont ete
    impactees par un mouvement donne. Permet de tracer precisement la
    consommation FIFO (une sortie peut prelever sur plusieurs lots)."""

    __tablename__ = "mouvement_lot"

    id = db.Column(db.Integer, primary_key=True)
    mouvement_id = db.Column(db.Integer, db.ForeignKey("mouvement.id"), nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey("lot.id"), nullable=False)
    quantite = db.Column(db.Float, nullable=False)

    lot = db.relationship("Lot")


# ---------------------------------------------------------------------------
# Utilisateurs et droits d'acces par depot
# ---------------------------------------------------------------------------

class Utilisateur(UserMixin, db.Model):
    """Compte utilisateur de l'application.

    - `est_admin` : acces total (lecture + ecriture sur tous les depots,
      gestion des utilisateurs), sans avoir besoin d'entrees AccesDepot.
    - Pour un utilisateur non-admin, les droits sont definis dépôt par dépôt
      via la table `AccesDepot` (lecture et/ou ecriture).
    - `recevoir_alertes_email` : opt-in pour recevoir les notifications par
      mail des alertes de stock de securite.
    """

    __tablename__ = "utilisateur"

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    mot_de_passe_hash = db.Column(db.String(255), nullable=False)

    est_admin = db.Column(db.Boolean, default=False, nullable=False)
    actif = db.Column(db.Boolean, default=True, nullable=False)
    recevoir_alertes_email = db.Column(db.Boolean, default=False, nullable=False)

    # Niveau hierarchique (voir NiveauUtilisateur), utilise pour autoriser
    # l'annulation d'un mouvement : seul un niveau strictement superieur a
    # celui de l'auteur du mouvement peut l'annuler.
    niveau = db.Column(db.Integer, nullable=False, default=NiveauUtilisateur.STANDARD)

    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    acces_depots = db.relationship(
        "AccesDepot", backref="utilisateur", lazy="dynamic", cascade="all, delete-orphan"
    )

    def definir_mot_de_passe(self, mot_de_passe_clair):
        self.mot_de_passe_hash = generate_password_hash(mot_de_passe_clair)

    def verifier_mot_de_passe(self, mot_de_passe_clair):
        return check_password_hash(self.mot_de_passe_hash, mot_de_passe_clair)

    # Flask-Login utilise get_id() ; par defaut il renvoie str(self.id) via UserMixin,
    # mais on le rend explicite pour la clarte.
    def get_id(self):
        return str(self.id)

    # -- Raccourcis de permissions -------------------------------------

    def peut_lire_depot(self, depot_id):
        if self.est_admin:
            return True
        return self.acces_depots.filter_by(depot_id=depot_id, peut_lire=True).first() is not None

    def peut_ecrire_depot(self, depot_id):
        if self.est_admin:
            return True
        return self.acces_depots.filter_by(depot_id=depot_id, peut_ecrire=True).first() is not None

    @property
    def depots_lecture_ids(self):
        if self.est_admin:
            return None  # None = tous les depots (consolide complet)
        return [a.depot_id for a in self.acces_depots if a.peut_lire]

    @property
    def depots_ecriture_ids(self):
        if self.est_admin:
            return None
        return [a.depot_id for a in self.acces_depots if a.peut_ecrire]

    @property
    def niveau_effectif(self):
        """Niveau reellement applique pour les comparaisons hierarchiques :
        un administrateur (`est_admin`) est toujours considere de niveau
        maximal, meme si le champ `niveau` n'a pas ete explicitement releve."""
        if self.est_admin:
            return NiveauUtilisateur.ADMINISTRATEUR
        return self.niveau or NiveauUtilisateur.STANDARD

    @property
    def niveau_libelle(self):
        return NiveauUtilisateur.libelle(self.niveau_effectif)

    def __repr__(self):
        return f"<Utilisateur {self.email}>"


class AccesDepot(db.Model):
    """Droit d'un utilisateur sur un depot donne : lecture (consultation des
    stocks/rapports de ce depot) et/ou ecriture (saisie d'entrees/sorties)."""

    __tablename__ = "acces_depot"
    __table_args__ = (db.UniqueConstraint("utilisateur_id", "depot_id", name="uq_acces_depot"),)

    id = db.Column(db.Integer, primary_key=True)
    utilisateur_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"), nullable=False)
    depot_id = db.Column(db.Integer, db.ForeignKey("depot.id"), nullable=False)

    peut_lire = db.Column(db.Boolean, default=True, nullable=False)
    peut_ecrire = db.Column(db.Boolean, default=False, nullable=False)

    depot = db.relationship("Depot")

    def __repr__(self):
        return f"<AccesDepot utilisateur={self.utilisateur_id} depot={self.depot_id}>"
