import pandas as pd
import os

csv_path = r'E:\ai\appartements_bourges.csv'
xlsx_path = r'E:\ai\appartements_bourges.xlsx'

try:
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path, sep=';')
        df.to_excel(xlsx_path, index=False)
        print("Conversion réussie")
    else:
        print("Le fichier CSV n'existe pas.")
except ImportError:
    print("Erreur: Les bibliothèques 'pandas' ou 'openpyxl' sont manquantes.")
except Exception as e:
    print(f"Erreur: {e}")
