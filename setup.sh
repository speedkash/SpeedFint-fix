#!/bin/bash

echo "📁 Création des dossiers..."
mkdir -p data/database
mkdir -p data/logs

echo "📦 Installation des dépendances..."
pip install -r requirements.txt

echo "✅ Installation terminée !"
