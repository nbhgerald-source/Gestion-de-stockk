# Application de Gestion de Stock

Application web (Flask) de gestion de stock avec :

- **Unite d'achat**, **colisage** et **unite de gestion de stock** par produit, avec facteur de conversion.
- **Categories de produits** : matieres premieres, accessoires, produits semi-finis, produits residuels, produits finis.
- **Suivi des entrees et sorties** avec **valorisation au Cout Unitaire Moyen Pondere (PMP / CUMP)**.
- **Gestion de lots** avec consommation en **FIFO** (premier entre, premier sorti) lors des sorties.
- **Stock de securite** par produit, avec **alertes** (rupture / sous le seuil) sur le tableau de bord.
- **Rapports de stock** journaliers, hebdomadaires, mensuels, trimestriels et annuels, exportables en CSV, **consolides ou par depot**.
- **Comptes utilisateurs et droits par depot** : lecture et/ou ecriture, accordes depot par depot (les administrateurs ont acces total).
- **Notifications par email** des alertes de stock de securite (envoi manuel depuis le tableau de bord, ou automatique apres une sortie qui fait passer un produit sous son seuil).
- **Tiers** (fournisseurs / clients-consommateurs) sur les entrees (origine) et les sorties
  (consommateur/destinataire), avec un **rapport d'analyse par tiers** (volumes et valeurs).
- **Import CSV** en masse : modele + chargement des articles, et modele + chargement du **stock
  initial** (entrees de depart, produit par produit et depot par depot).
- **Annulation d'un mouvement** par un utilisateur de **niveau hierarchique superieur** a celui
  qui l'a saisi (Standard < Superviseur < Administrateur), avec mouvement compensatoire
  (tracabilite complete, rien n'est supprime).

## Comment fonctionne la valorisation

- A chaque **entree**, un nouveau **lot** est cree avec son cout d'achat reel, et le **PMP** du produit est recalcule :
  `PMP = (Stock_avant x PMP_avant + Qte_entree x Cout_entree) / (Stock_avant + Qte_entree)`
- A chaque **sortie**, les lots sont consommes dans l'ordre **FIFO** (date d'entree la plus ancienne en premier) pour le suivi physique, mais la sortie est **valorisee au PMP courant** (methode comptable demandee). Le PMP n'est pas modifie par une sortie.

## Installation (local)

```bash
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # optionnel, garder DATABASE_URL vide pour SQLite
python run.py
```

L'application est alors disponible sur http://localhost:5000

Une base SQLite (`stock.db`) est creee automatiquement au premier lancement, avec
quelques unites de mesure de base (KG, PCE, CARTON...), un depot principal, et un
**compte administrateur par defaut** (identifiants affiches dans la console au premier
demarrage ; personnalisables via les variables d'environnement `ADMIN_EMAIL_DEFAUT` et
`ADMIN_MOTDEPASSE_DEFAUT`). Connectez-vous avec ce compte, puis changez son mot de passe
dans **Utilisateurs > Modifier**.

### Notifications par email (optionnel)

Sans configuration, les alertes de stock de securite sont simplement affichees dans la
console du serveur (mode test). Pour un envoi reel par email, definir ces variables
d'environnement avant de lancer l'application :

```
MAIL_SERVEUR=smtp.exemple.com
MAIL_PORT=587
MAIL_UTILISATEUR=...
MAIL_MOT_DE_PASSE=...
MAIL_EXPEDITEUR=stock@exemple.com
```

Seuls les utilisateurs ayant coche "Recevoir les alertes de stock par email" (dans leur
fiche **Utilisateurs**) recoivent ces notifications.

### Donnees de demonstration (optionnel)

Pour creer 2 produits d'exemple avec des mouvements (entrees a couts differents, une sortie en FIFO) :

```bash
python seed_demo.py
```

## Premiers pas dans l'application

1. Connectez-vous avec le compte administrateur par defaut (voir ci-dessus).
2. **Parametres > Unites de mesure** : verifiez/completez les unites (KG, PCE, CARTON, L...).
3. **Parametres > Depots** : creez vos depots si besoin (un depot "Principal" existe par defaut).
4. **Parametres > Utilisateurs** : creez un compte par collaborateur, et accordez a chacun les
   droits de **lecture** et/ou **ecriture** sur les depots concernes (un administrateur a
   automatiquement acces total a tous les depots).
5. **Produits > Nouveau produit** (administrateurs uniquement) : creez vos produits en precisant
   categorie, unite d'achat, unite de gestion, facteur de conversion (colisage) et stock de securite.
6. **Entree** / **Sortie** : enregistrez vos mouvements de stock, depot par depot (consommation
   FIFO automatique limitee au depot choisi, valorisation au PMP). Seuls les depots ou
   l'utilisateur a un droit d'**ecriture** apparaissent dans la liste.
7. **Rapports** : generez vos rapports de stock par periode (jour/semaine/mois/trimestre/annee),
   filtrables par categorie de produit et **consolides ou par depot**, exportables en CSV.
   Un utilisateur standard ne voit que les depots pour lesquels il a un droit de **lecture**.
   Le bouton **Analyse par tiers** agrege les memes mouvements par fournisseur/client.
8. **Parametres > Tiers** (administrateurs) : creez vos fournisseurs et clients/consommateurs,
   puis renseignez-les comme origine d'une entree ou destinataire d'une sortie.
9. **Parametres > Modele import produits / Importer des produits** et **Modele import stock
   initial / Importer le stock initial** (administrateurs) : chargement en masse via CSV.

## Import CSV en masse (produits et stock initial)

Deux assistants d'import sont accessibles depuis **Parametres** (administrateurs uniquement) :

- **Produits** : telechargez le modele CSV (colonnes `code`, `designation`, `type_produit`,
  `unite_achat_code`, `unite_gestion_code`, `facteur_conversion`, `libelle_colisage`,
  `stock_securite`), completez-le, puis importez-le. Les unites referencees doivent deja exister.
- **Stock initial** : telechargez le modele CSV (colonnes `code_produit`, `depot_code`,
  `quantite`, `cout_unitaire`, `date_entree`, `numero_lot`, `reference`), completez-le une fois
  vos produits et depots crees, puis importez-le : chaque ligne enregistre une entree de stock
  (un lot), comme une saisie manuelle.

Les deux imports sont **tout-ou-rien** : si une seule ligne est invalide, rien n'est enregistre et
la liste des erreurs (numero de ligne + raison) est affichee.

## Annulation d'un mouvement

Chaque utilisateur a un **niveau hierarchique** (**Parametres > Utilisateurs**) : Standard,
Superviseur ou Administrateur (un compte Administrateur est toujours considere de niveau
maximal). Sur la page **Mouvements**, un bouton **Annuler** apparait sur un mouvement si :

- l'utilisateur connecte a un niveau **strictement superieur** a celui de l'auteur du mouvement
  (un Standard ne peut donc jamais annuler, meme ses propres erreurs) ;
- il a un droit d'**ecriture** sur le depot concerne ;
- et c'est le **tout dernier mouvement enregistre pour ce produit** (l'annulation d'un mouvement
  plus ancien casserait la coherence du PMP et des lots ; pour le corriger, faites un mouvement
  correctif classique).

L'annulation ne supprime rien : le mouvement original est marque "Annule" et un **mouvement
compensatoire** est cree pour neutraliser son effet sur le stock, le PMP et les lots.

## Droits d'acces par depot

- **Administrateur** (`est_admin`) : acces total en lecture et ecriture sur tous les depots, et
  seul profil pouvant gerer les produits, parametres et autres utilisateurs.
- **Utilisateur standard** : acces defini depot par depot dans **Utilisateurs > Modifier**, avec
  deux cases independantes par depot : **Lecture** (consultation du stock et des rapports de ce
  depot) et **Ecriture** (saisie d'entrees/sorties dans ce depot). Un utilisateur sans aucun acces
  configure ne voit aucune donnee de stock.
- Le rapport "Consolide" agrege soit tous les depots (administrateur), soit uniquement les depots
  ou l'utilisateur a un droit de lecture (utilisateur standard).

## Deploiement en cloud (acces multi-utilisateurs a distance)

L'application est une app Flask standard, deployable sur n'importe quel hebergeur
(Render, Railway, Heroku, un VPS, etc.). Etapes generales :

1. Provisionner une base **PostgreSQL** (la plupart des hebergeurs cloud en proposent une).
2. Installer le pilote PostgreSQL (non requis en local avec SQLite, voir
   `requirements-postgresql.txt`) :
   ```bash
   pip install -r requirements-postgresql.txt
   ```
3. Definir les variables d'environnement :
   - `DATABASE_URL` = URL de connexion PostgreSQL fournie par l'hebergeur
   - `SECRET_KEY` = une valeur secrete aleatoire
4. Lancer l'application avec un serveur de production WSGI, par exemple avec **gunicorn** :
   ```bash
   pip install gunicorn
   gunicorn "app:create_app()" --bind 0.0.0.0:8000
   ```
5. Configurer un acces HTTPS (la plupart des hebergeurs cloud le font automatiquement).

Au premier demarrage sur la nouvelle base, les tables et les unites/depot de base sont
crees automatiquement (comme en local).

## Structure du projet

```
app/
  models.py              Modeles (Produit, UniteMesure, Depot, Lot, Mouvement, MouvementLot,
                          Tiers, Utilisateur, AccesDepot)
  extensions.py          Initialisation SQLAlchemy + Flask-Login
  seed.py                Donnees de base (unites, depot principal, admin par defaut)
  services/
    stock_service.py     Entrees/sorties, calcul PMP, consommation FIFO (depot-aware), alertes
    report_service.py    Calcul des rapports de stock par periode (consolide/par depot/par tiers)
    permissions.py        Droits d'acces par depot (lecture/ecriture), decorateur admin_requis
    mail_service.py        Envoi des notifications email d'alerte stock
  routes/
    auth.py                 Connexion / deconnexion
    main.py                 Tableau de bord, envoi manuel des alertes par email
    produits.py            CRUD produits (creation/modification reservees aux administrateurs)
    parametres.py          CRUD unites de mesure / depots (administrateurs)
    mouvements.py          Saisie entrees/sorties par depot, historique, annulation
    rapports.py             Rapports periodiques (consolide ou par depot) + export CSV
    utilisateurs.py         Gestion des comptes et droits par depot (administrateurs)
  templates/              Pages HTML (Bootstrap 5)
run.py                    Point d'entree (developpement local)
seed_demo.py               Donnees de demonstration (optionnel)
config.py                  Configuration (base de donnees, cles, SMTP)
requirements.txt
```

## Limites connues / pistes d'evolution

- Le PMP reste un cout moyen unique par produit, **non decline par depot** : un rapport
  filtre par depot affiche les quantites de ce depot mais valorise au PMP global de
  l'entreprise (un suivi de cout separe par depot demanderait un PMP par (produit, depot)).
- Les notifications email utilisent un envoi synchrone (smtplib) au moment de la sortie ou
  du clic "Envoyer par email" ; pour un volume important, une file d'attente (Celery, RQ...)
  serait preferable.
- Pas de reinitialisation de mot de passe en self-service (un administrateur doit le faire
  manuellement dans Utilisateurs > Modifier).
- **Mise a jour d'une base existante** : il n'y a pas d'outil de migration (Alembic). Au
  demarrage, l'application cree uniquement les **tables manquantes** (`db.create_all()`), pas
  les colonnes manquantes sur une table existante. Si vous avez deja une base `stock.db` creee
  avant l'ajout des **tiers**, lancez une seule fois, **sans perte de donnees** :
  ```bash
  python migrer_ajout_tiers.py
  ```
  Ce script ajoute la table `tiers` et la colonne `mouvement.tiers_id` si elles manquent (sans
  rien supprimer), puis vous pouvez relancer l'application normalement (`python run.py`).
