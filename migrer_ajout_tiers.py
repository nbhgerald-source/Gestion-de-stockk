"""Script de migration ponctuel pour les bases SQLite existantes (stock.db
creees avant l'ajout des fonctionnalites "Tiers" et "Annulation de mouvement".

Pourquoi ce script est necessaire :
    Au demarrage, l'application appelle `db.create_all()`, qui cree
    uniquement les TABLES MANQUANTES, mais PAS les colonnes manquantes sur
    une table qui existe deja. Si votre base a ete creee avant l'ajout de
    ces fonctionnalites, plusieurs colonnes manqueront (ex: erreur SQL
    "no such column: mouvement.tiers_id" ou "no such column: mouvement.annule").

Ce script regroupe TOUTES les migrations additives connues a ce jour. Il est :
    - Idempotent : si une colonne/table existe deja, elle est ignoree (peut
      etre relance sans risque, y compris plusieurs fois).
    - Non destructif : il n'efface aucune donnee.

Usage :
    python migrer_ajout_tiers.py
"""

import os
import sqlite3

CHEMIN_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock.db")


def colonne_existe(cur, table, colonne):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == colonne for row in cur.fetchall())


def table_existe(cur, table):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def ajouter_colonne_si_absente(cur, table, colonne, definition_sql):
    if not colonne_existe(cur, table, colonne):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {definition_sql}")
        print(f"Colonne '{table}.{colonne}' ajoutee.")
    else:
        print(f"Colonne '{table}.{colonne}' deja presente, pas de changement.")


def main():
    if not os.path.exists(CHEMIN_BASE):
        print(
            f"Aucune base trouvee a {CHEMIN_BASE}. "
            "Rien a migrer (une base neuve sera creee avec le bon schema au premier lancement)."
        )
        return

    con = sqlite3.connect(CHEMIN_BASE)
    cur = con.cursor()

    try:
        if not table_existe(cur, "mouvement"):
            print("La table 'mouvement' n'existe pas encore : rien a migrer pour l'instant.")
            return

        # --- Fonctionnalite "Tiers" (origine/consommateur) -----------------

        if not table_existe(cur, "tiers"):
            cur.execute(
                """
                CREATE TABLE tiers (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    code VARCHAR(30) NOT NULL UNIQUE,
                    nom VARCHAR(150) NOT NULL,
                    type_tiers VARCHAR(20) NOT NULL DEFAULT 'AUTRE',
                    actif BOOLEAN NOT NULL DEFAULT 1
                )
                """
            )
            print("Table 'tiers' creee.")
        else:
            print("Table 'tiers' deja presente, pas de changement.")

        ajouter_colonne_si_absente(cur, "mouvement", "tiers_id", "INTEGER REFERENCES tiers(id)")

        # --- Fonctionnalite "Annulation de mouvement" -----------------------

        ajouter_colonne_si_absente(cur, "mouvement", "annule", "BOOLEAN NOT NULL DEFAULT 0")
        ajouter_colonne_si_absente(cur, "mouvement", "est_annulation", "BOOLEAN NOT NULL DEFAULT 0")
        ajouter_colonne_si_absente(
            cur, "mouvement", "mouvement_origine_id", "INTEGER REFERENCES mouvement(id)"
        )
        ajouter_colonne_si_absente(cur, "mouvement", "annule_par", "VARCHAR(100)")
        ajouter_colonne_si_absente(cur, "mouvement", "date_annulation", "DATETIME")

        if table_existe(cur, "utilisateur"):
            ajouter_colonne_si_absente(cur, "utilisateur", "niveau", "INTEGER NOT NULL DEFAULT 1")

        con.commit()
        print("Migration terminee avec succes. Vous pouvez relancer l'application (python run.py).")
    finally:
        con.close()


if __name__ == "__main__":
    main()
