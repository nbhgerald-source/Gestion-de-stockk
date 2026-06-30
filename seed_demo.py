"""Script optionnel pour generer des donnees de demonstration
(produits, entrees, sorties) et verifier rapidement le fonctionnement de l'application.

Usage :
    python seed_demo.py
"""

from datetime import date, timedelta

from app import create_app
from app.extensions import db
from app.models import Depot, Produit, TypeProduit, UniteMesure
from app.services.stock_service import enregistrer_entree, enregistrer_sortie

app = create_app()

with app.app_context():
    kg = UniteMesure.query.filter_by(code="KG").first()
    carton = UniteMesure.query.filter_by(code="CARTON").first()
    pce = UniteMesure.query.filter_by(code="PCE").first()
    depot = Depot.query.filter_by(code="PRINCIPAL").first()

    if not Produit.query.filter_by(code="MP-001").first():
        mp = Produit(
            code="MP-001",
            designation="Farine de ble (matiere premiere)",
            type_produit=TypeProduit.MATIERE_PREMIERE,
            unite_achat_id=carton.id,
            unite_gestion_id=kg.id,
            facteur_conversion=25.0,  # 1 sac/carton de 25 kg
            libelle_colisage="Sac de 25 kg",
            stock_securite=100.0,
        )
        db.session.add(mp)
        db.session.commit()

        # Entree 1 : il y a 20 jours, prix plus eleve
        enregistrer_entree(
            mp, quantite=10, cout_unitaire=30.0, unite="ACHAT",
            date_entree=date.today() - timedelta(days=20),
            depot_id=depot.id, reference="BL-1001", motif="Achat fournisseur A",
        )
        # Entree 2 : il y a 5 jours, prix plus bas -> recalcul du PMP
        enregistrer_entree(
            mp, quantite=8, cout_unitaire=27.0, unite="ACHAT",
            date_entree=date.today() - timedelta(days=5),
            depot_id=depot.id, reference="BL-1042", motif="Achat fournisseur B",
        )
        # Sortie : consommee en FIFO sur le lot le plus ancien d'abord
        enregistrer_sortie(
            mp, quantite=120, unite="GESTION", depot_id=depot.id,
            reference="OF-5001", motif="Production",
        )

        print(f"Produit demo cree : {mp.code} - stock={mp.quantite_stock} kg - PMP={mp.pmp}")

    if not Produit.query.filter_by(code="PF-001").first():
        pf = Produit(
            code="PF-001",
            designation="Pain de mie (produit fini)",
            type_produit=TypeProduit.PRODUIT_FINI,
            unite_achat_id=pce.id,
            unite_gestion_id=pce.id,
            facteur_conversion=1.0,
            stock_securite=50.0,
        )
        db.session.add(pf)
        db.session.commit()
        enregistrer_entree(
            pf, quantite=200, cout_unitaire=1.2, unite="GESTION",
            depot_id=depot.id, reference="OF-5001", motif="Sortie de production",
        )
        print(f"Produit demo cree : {pf.code} - stock={pf.quantite_stock} pce - PMP={pf.pmp}")

print("Donnees de demonstration inserees avec succes.")
