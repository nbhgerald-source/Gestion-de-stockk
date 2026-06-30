@echo off
REM ============================================================
REM  Script de publication GitHub - SIPACO Stock doolee
REM  Double-cliquez sur ce fichier apres avoir cree le depot
REM  sur github.com/new (voir instructions ci-dessous).
REM ============================================================

set PROJET=%~dp0
cd /d "%PROJET%"

echo ============================================================
echo  SIPACO - Publication sur GitHub
echo ============================================================
echo.
echo  Avant de continuer, assurez-vous d'avoir :
echo  1. Cree un depot VIDE sur https://github.com/new
echo     (sans README, sans .gitignore, sans licence)
echo  2. Copie l'URL du depot (ex: https://github.com/moncompte/sipaco-stock-doolee.git)
echo.
set /p REPO_URL="Collez l'URL du depot GitHub ici puis Entree : "

echo.
echo  Initialisation de Git...
git init

echo  Ajout de tous les fichiers...
git add .

echo  Premier commit...
git commit -m "Initial commit - Application de gestion de stock SIPACO doolee"

echo  Definition de la branche principale...
git branch -M main

echo  Connexion au depot distant...
git remote add origin %REPO_URL%

echo  Envoi du code sur GitHub...
git push -u origin main

echo.
echo ============================================================
echo  SUCCES ! Votre code est maintenant sur GitHub.
echo ============================================================
echo.
echo  Prochaine etape - Deploiement sur Render :
echo  1. Allez sur https://dashboard.render.com
echo  2. Cliquez "New" puis "Blueprint"
echo  3. Connectez votre depot GitHub
echo  4. Render detecte render.yaml et deploie automatiquement
echo.
pause
